"""
Pipeline entry point: fetch arxiv articles for the current ISO week, apply the
inclusion filter, and write docs/arxiv/{category}/atom.xml.

Environment variables read by this module:
  ARXIV_API_BASE_URL           optional; default "https://export.arxiv.org"
  ARXIV_CATEGORY_ID            optional; default "cs.AI"
  ARXIV_CATEGORY_STRICT        optional; "true" enables strict primary-category filter
  ARXIV_CONTINUE_ON_API_ERROR  optional; "true" exits 0 on API failure instead of 1
  ARXIV_MAX_RESULTS            optional; entries per API page; default 50
  ARXIV_MAX_STALENESS_DAYS     optional; days before feed is considered stale; default -1 (disabled)
  GITHUB_REPOSITORY            required; "owner/repo" (always set by GitHub Actions)
  PIPELINE_TODAY               optional; ISO date (YYYY-MM-DD) overrides the current UTC date
  RETRY_BACKOFF_BASE_SECONDS   optional; seconds for exponential retry backoff; default 60
"""

import datetime
import difflib
import html
import io
import json
import logging
import os
import pathlib
import re
import sys
import time
import typing
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

# Register the Atom namespace as the default so the serialiser writes
# <feed xmlns="..."> rather than <ns0:feed xmlns:ns0="...">.
ET.register_namespace("", _ATOM_NS)

# NFR-002: minimum pause before every API request to respect arxiv rate limits.
_MIN_REQUEST_INTERVAL_SECONDS: int = 5

# Arxiv categories follow the pattern subject(-subsubject)?(.archive)?
# e.g. cs.AI, cs.cv, astro-ph.HE, gr-qc. Letters only; no path separators,
# whitespace, or directory-traversal sequences are permitted. This guards
# against accidental misconfiguration and path-traversal values such as
# "../etc/passwd" reaching the docs/arxiv/{category}/ filesystem path.
_ARXIV_CATEGORY_PATTERN = re.compile(r"^[a-zA-Z]+(-[a-zA-Z]+)?(\.[a-zA-Z]+)?$")

# Code-hosting domains accepted as code-availability signals in abstracts
# and PDF text.  Comment URLs accept any https:// URL regardless of domain.
ACCEPTED_REPO_DOMAINS: frozenset[str] = frozenset({
    "github.com",
    "gitlab.com",
    "huggingface.co",
})

# Domain suffixes that match any subdomain (e.g. ".github.io" matches
# "user.github.io").
ACCEPTED_REPO_DOMAIN_SUFFIXES: frozenset[str] = frozenset({
    ".github.io",
})

_logger = logging.getLogger(__name__)


class Article(typing.NamedTuple):
    """One arxiv article: the fields extracted from the API response and consumed by the feed builder.

    authors and comment_urls are list[str] rather than tuple[str, ...] so that
    test code can compare them against literal lists with the == operator.
    repo_found_in and repo_urls are populated by the enrichment cascade; they
    default to empty so that parse_entries and test constructors need not
    specify them.
    """

    title: str
    authors: list[str]
    primary_category: str
    abstract_url: str
    published: str
    updated: str
    abstract: str
    comment: str | None
    comment_urls: list[str]
    repo_found_in: str = ""
    repo_urls: tuple[str, ...] = ()


class _UtcJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects with UTC timestamps."""

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        """Return a JSON string with asctime, levelname, name, funcName, message."""
        return json.dumps({
            "asctime": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "levelname": record.levelname,
            "name": record.name,
            "funcName": record.funcName,
            "message": record.getMessage(),
        })


def _is_not_error(record: logging.LogRecord) -> bool:
    """Accept log records with level below ERROR (INFO and DEBUG only)."""
    return record.levelno < logging.ERROR


# ---------------------------------------------------------------------------
# Environment / configuration resolution
# ---------------------------------------------------------------------------


def resolve_category_id() -> str:
    """Return ARXIV_CATEGORY_ID from the environment, defaulting to 'cs.AI'."""
    value = os.environ.get("ARXIV_CATEGORY_ID", "cs.AI")
    if not _ARXIV_CATEGORY_PATTERN.match(value):
        raise ValueError(
            f"ARXIV_CATEGORY_ID does not match arxiv category format: {value!r}"
        )
    return value


def resolve_strict_mode() -> bool:
    """
    Return True when ARXIV_CATEGORY_STRICT is the case-insensitive literal
    'true'; return False for any other value, including unset.
    """
    return os.environ.get("ARXIV_CATEGORY_STRICT", "").lower() == "true"


def resolve_continue_on_api_error() -> bool:
    """
    Return True when ARXIV_CONTINUE_ON_API_ERROR is the case-insensitive
    literal 'true'; return False for any other value, including unset.

    Follows the same convention as resolve_strict_mode.
    """
    return os.environ.get("ARXIV_CONTINUE_ON_API_ERROR", "").lower() == "true"


def _validate_staleness_days(value: str) -> int:
    """
    Parse ARXIV_MAX_STALENESS_DAYS as an integer and validate the range.

    Accepts -1 (disabled) and any positive integer.  Raises ValueError for
    any other input, including 0, negative integers other than -1, and
    non-integer strings.  The error message names the variable and quotes
    the offending value so the caller can log it directly.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(
            f"ARXIV_MAX_STALENESS_DAYS must be -1 or a positive integer, got: {value!r}"
        )
    if parsed != -1 and parsed < 1:
        raise ValueError(
            f"ARXIV_MAX_STALENESS_DAYS must be -1 or a positive integer, got: {parsed}"
        )
    return parsed


def resolve_max_backfill_days() -> int:
    """Return ARXIV_MAX_BACKFILL_DAYS from the environment, defaulting to 8.

    Accepts positive integers only (minimum 1).  Raises ValueError for zero,
    negative integers, or non-integer strings.
    """
    value = os.environ.get("ARXIV_MAX_BACKFILL_DAYS", "8")
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(
            f"ARXIV_MAX_BACKFILL_DAYS must be a positive integer, got: {value!r}"
        )
    if parsed < 1:
        raise ValueError(
            f"ARXIV_MAX_BACKFILL_DAYS must be a positive integer, got: {parsed}"
        )
    return parsed


def _resolve_today() -> datetime.date:
    """Return PIPELINE_TODAY if set, otherwise the current UTC date."""
    override = os.environ.get("PIPELINE_TODAY")
    if override:
        return datetime.date.fromisoformat(override)
    return datetime.datetime.now(datetime.timezone.utc).date()


def _parse_rfc3339_utc_date(timestamp: str) -> datetime.date:
    """Parse an RFC 3339 timestamp and return its UTC date.

    fromisoformat handles the "Z" UTC suffix in Python 3.11+; the result is
    converted to UTC before the date portion is taken so that timestamps
    expressed in other offsets still yield the UTC calendar date.
    """
    return (
        datetime.datetime.fromisoformat(timestamp)
        .astimezone(datetime.timezone.utc)
        .date()
    )


# ---------------------------------------------------------------------------
# Article inclusion filter and enrichment cascade
# ---------------------------------------------------------------------------


def _is_url_on_accepted_domain(
    url: str,
    accepted_domains: frozenset[str],
    accepted_suffixes: frozenset[str],
) -> bool:
    """Return True when url's hostname matches any accepted domain or suffix."""
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in accepted_domains:
        return True
    return any(hostname.endswith(suffix) for suffix in accepted_suffixes)


def extract_repo_urls(
    text: str,
    accepted_domains: frozenset[str] | None = None,
    accepted_suffixes: frozenset[str] | None = None,
) -> list[str]:
    """Extract accepted-domain URLs from free-form text (abstract or PDF).

    Two regex passes are applied:
    1. https://\\S+ captures scheme-prefixed URLs.
    2. A bare-domain regex for each accepted domain and suffix captures URLs
       that appear without the https:// scheme (e.g. when LaTeX renders a
       URL via \\href{url}{icon}).

    Trailing punctuation from the set .,;:)]> is stripped from each match.
    Results are deduplicated and filtered to the accepted domain set.
    """
    if not text:
        return []

    domains = accepted_domains if accepted_domains is not None else ACCEPTED_REPO_DOMAINS
    suffixes = accepted_suffixes if accepted_suffixes is not None else ACCEPTED_REPO_DOMAIN_SUFFIXES

    raw_urls: list[str] = []

    for match in re.findall(r"https://\S+", text):
        raw_urls.append(match.rstrip(".,;:)]>"))

    bare_parts: list[str] = []
    for domain in sorted(domains):
        bare_parts.append(re.escape(domain))
    for suffix in sorted(suffixes):
        bare_parts.append(r"\S+" + re.escape(suffix))
    if bare_parts:
        bare_regex = f"(?:{'|'.join(bare_parts)})/\\S+"
        for match in re.findall(bare_regex, text):
            raw_urls.append(f"https://{match.rstrip('.,;:)]>')}")

    seen: set[str] = set()
    filtered: list[str] = []
    for url in raw_urls:
        if url in seen:
            continue
        seen.add(url)
        if _is_url_on_accepted_domain(url, domains, suffixes):
            filtered.append(url)

    return filtered


def enrich_from_metadata(
    article: Article,
    accepted_domains: frozenset[str] | None = None,
    accepted_suffixes: frozenset[str] | None = None,
) -> Article:
    """Set repo_found_in and repo_urls from comment or abstract URLs.

    Cascade: comment URLs (any https://) take priority; abstract URLs
    (accepted domains only) are the fallback.  Returns article unchanged
    when neither source yields a URL.
    """
    if article.comment_urls:
        return article._replace(
            repo_found_in="comment",
            repo_urls=tuple(sorted(set(article.comment_urls))),
        )

    abstract_urls = extract_repo_urls(
        article.abstract,
        accepted_domains=accepted_domains,
        accepted_suffixes=accepted_suffixes,
    )
    if abstract_urls:
        return article._replace(
            repo_found_in="abstract",
            repo_urls=tuple(sorted(set(abstract_urls))),
        )

    return article


def extract_pdf_repo_urls(
    pdf_bytes: bytes,
    max_pages: int = 10,
    accepted_domains: frozenset[str] | None = None,
    accepted_suffixes: frozenset[str] | None = None,
) -> list[str]:
    """Extract accepted-domain URLs from PDF pages, stopping before References.

    Three extraction layers per page, applied in order:
    1. Link annotations (/Link with /A /URI) -- most reliable, full URIs
       from PDF hyperlink metadata.
    2. Text https://\\S+ regex -- catches scheme-prefixed visible URLs.
    3. Text bare domain regex -- catches URLs without https:// scheme
       (e.g. when LaTeX renders \\href{url}{icon}).

    Scanning stops when a page contains a standalone "References" or
    "REFERENCES" line; that page and all subsequent pages are skipped.

    Returns sorted, deduplicated, domain-filtered URLs.
    """
    import pypdf

    domains = accepted_domains if accepted_domains is not None else ACCEPTED_REPO_DOMAINS
    suffixes = accepted_suffixes if accepted_suffixes is not None else ACCEPTED_REPO_DOMAIN_SUFFIXES

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    raw_urls: list[str] = []

    for page_index in range(min(len(reader.pages), max_pages)):
        page = reader.pages[page_index]
        text = page.extract_text() or ""

        if re.search(r"(?m)^\s*(?:References|REFERENCES)\s*$", text):
            break

        if page.annotations:
            for annotation in page.annotations:
                annotation_obj = annotation.get_object()
                if annotation_obj.get("/Subtype") == "/Link":
                    action = annotation_obj.get("/A")
                    if action:
                        uri = action.get("/URI")
                        if uri:
                            raw_urls.append(str(uri))

        for match in re.findall(r"https://\S+", text):
            raw_urls.append(match.rstrip(".,;:)]>"))

        bare_parts: list[str] = []
        for domain in sorted(domains):
            bare_parts.append(re.escape(domain))
        for suffix in sorted(suffixes):
            bare_parts.append(r"\S+" + re.escape(suffix))
        if bare_parts:
            bare_regex = f"(?:{'|'.join(bare_parts)})/\\S+"
            for match in re.findall(bare_regex, text):
                raw_urls.append(f"https://{match.rstrip('.,;:)]>')}")

    seen: set[str] = set()
    filtered: list[str] = []
    for url in raw_urls:
        if url in seen:
            continue
        seen.add(url)
        if _is_url_on_accepted_domain(url, domains, suffixes):
            filtered.append(url)

    return sorted(filtered)


def _default_fetch_pdf(url: str) -> bytes:
    """Fetch PDF bytes from url with a rate-limit pause (NFR-002)."""
    time.sleep(_MIN_REQUEST_INTERVAL_SECONDS)
    with urllib.request.urlopen(url) as response:
        return response.read()


def enrich_from_pdf(
    article: Article,
    accepted_domains: frozenset[str] | None = None,
    accepted_suffixes: frozenset[str] | None = None,
    _fetch_pdf: typing.Callable[[str], bytes] | None = None,
) -> Article | None:
    """Enrich article with repo URLs extracted from its PDF body.

    Skips articles already enriched (repo_found_in is non-empty).
    Downloads the PDF from export.arxiv.org and runs extract_pdf_repo_urls.
    Returns None on any error so the caller can exclude failed articles
    from the processed dict and retry them on the next run.
    """
    if article.repo_found_in:
        return article

    fetcher = _fetch_pdf if _fetch_pdf is not None else _default_fetch_pdf

    try:
        arxiv_id = article.abstract_url.rsplit("/", 1)[-1]
        pdf_url = f"https://export.arxiv.org/pdf/{arxiv_id}"
        pdf_bytes = fetcher(pdf_url)
        urls = extract_pdf_repo_urls(
            pdf_bytes,
            accepted_domains=accepted_domains,
            accepted_suffixes=accepted_suffixes,
        )
        if urls:
            return article._replace(
                repo_found_in="pdf",
                repo_urls=tuple(sorted(set(urls))),
            )
        return article
    except Exception as exc:
        _logger.error(
            "PDF enrichment failed for %s: %s", article.abstract_url, exc
        )
        return None


def matches_category(
    article: Article, category_id: str, strict_mode: bool
) -> bool:
    """Return True when the article's primary category passes the category filter.

    Non-strict mode (default) accepts any primary category.
    Strict mode requires a case-insensitive match with category_id.
    """
    if not strict_mode:
        return True
    if article.primary_category.lower() != category_id.lower():
        _logger.info(
            "rejected (strict category mismatch): primary=%s expected=%s"
            " published=%s title=%s url=%s",
            article.primary_category, category_id, article.published,
            article.title, article.abstract_url,
        )
        return False
    return True


def include_article(article: Article) -> bool:
    """Return True when the article has a code-availability URL from any cascade source.

    The enrichment cascade (enrich_from_metadata or enrich_from_pdf) must
    have run before calling this function; it checks repo_found_in which is
    set by the cascade.
    """
    if article.repo_found_in:
        _logger.info(
            "included: source=%s primary=%s published=%s title=%s url=%s",
            article.repo_found_in, article.primary_category,
            article.published, article.title, article.abstract_url,
        )
        return True
    _logger.info(
        "rejected (no code URL): primary=%s published=%s title=%s url=%s",
        article.primary_category, article.published, article.title,
        article.abstract_url,
    )
    return False


# ---------------------------------------------------------------------------
# API fetching and XML parsing
# ---------------------------------------------------------------------------


def compute_week_bounds(today: datetime.date) -> tuple[str, str]:
    """
    Return (monday, sunday) as YYYYMMDD strings for the ISO week that
    contains today.  Monday is weekday 0; Sunday is weekday 6.
    """
    monday = today - datetime.timedelta(days=today.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday.strftime("%Y%m%d"), sunday.strftime("%Y%m%d")


def build_api_url(
    base_url: str,
    category_id: str,
    monday: str,
    sunday: str,
    start: int,
    max_results: int,
) -> str:
    """
    Construct the arxiv API query URL.

    The query uses literal + for AND and square brackets for date ranges as
    required by the arxiv API user manual.  These characters are left
    unencoded because the arxiv server expects this exact form.
    """
    search_query = (
        f"cat:{category_id}+AND+submittedDate:[{monday}0000+TO+{sunday}2359]"
    )
    return (
        f"{base_url}/api/query"
        f"?search_query={search_query}"
        f"&start={start}"
        f"&max_results={max_results}"
        f"&sortBy=submittedDate"
        f"&sortOrder=descending"
    )


def _fetch_page(url: str) -> tuple[int, bytes]:
    """Return (http_status, body_bytes) for a GET request to url."""
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def extract_comment_urls(comment: str | None) -> list[str]:
    """
    Extract all https:// URLs from comment in order of appearance.

    Trailing characters from the set .,;:)]> are stripped from each URL to
    handle common punctuation that surrounds URLs in prose (e.g. "see
    https://example.com/x.").  Scheme-only results (bare "https://") that
    arise from stripping all content after the scheme — e.g. a comment
    containing "https://." — are excluded.  Returns an empty list when
    comment is None or empty.
    """
    if not comment:
        return []
    stripped = [
        url.rstrip(".,;:)]>") for url in re.findall(r"https://\S+", comment)
    ]
    return [url for url in stripped if url != "https://"]


def parse_entries(body: bytes) -> list[Article]:
    """
    Parse an arxiv Atom XML response and return one Article per <entry>.

    The following XML elements are extracted into the corresponding Article
    fields:
      atom:title                                       -> title
      atom:author/atom:name (document order)           -> authors
      arxiv:primary_category/@term                     -> primary_category
      atom:link[@rel='alternate'][@type='text/html']   -> abstract_url
      atom:published                                   -> published
      atom:updated                                     -> updated
      atom:summary (or "" if absent)                   -> abstract
      arxiv:comment (or None if absent)                -> comment
      comment_urls is computed from comment by extract_comment_urls.
    """
    root = ET.fromstring(body)
    articles: list[Article] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        title_elem = entry.find(f"{{{_ATOM_NS}}}title")
        title = title_elem.text if title_elem is not None else ""

        authors: list[str] = []
        for author_elem in entry.findall(f"{{{_ATOM_NS}}}author"):
            name_elem = author_elem.find(f"{{{_ATOM_NS}}}name")
            if name_elem is not None:
                authors.append(name_elem.text or "")

        primary_cat_elem = entry.find(f"{{{_ARXIV_NS}}}primary_category")
        primary_category = (
            primary_cat_elem.get("term", "")
            if primary_cat_elem is not None
            else ""
        )

        abstract_url = ""
        for link_elem in entry.findall(f"{{{_ATOM_NS}}}link"):
            if (
                link_elem.get("rel") == "alternate"
                and link_elem.get("type") == "text/html"
            ):
                abstract_url = link_elem.get("href", "")
                break

        published_elem = entry.find(f"{{{_ATOM_NS}}}published")
        published = published_elem.text if published_elem is not None else ""

        updated_elem = entry.find(f"{{{_ATOM_NS}}}updated")
        updated = updated_elem.text if updated_elem is not None else ""

        abstract_elem = entry.find(f"{{{_ATOM_NS}}}summary")
        abstract = abstract_elem.text if abstract_elem is not None else ""

        comment_elem = entry.find(f"{{{_ARXIV_NS}}}comment")
        comment: str | None = (
            comment_elem.text if comment_elem is not None else None
        )

        articles.append(
            Article(
                title=title or "",
                authors=authors,
                primary_category=primary_category,
                abstract_url=abstract_url,
                published=published or "",
                updated=updated or "",
                abstract=abstract or "",
                comment=comment,
                comment_urls=extract_comment_urls(comment),
            )
        )
    return articles


# ---------------------------------------------------------------------------
# Feed building
# ---------------------------------------------------------------------------


def build_github_repo_url(github_repository: str) -> str:
    """Return the GitHub repository URL for a "owner/repo" identifier."""
    owner, repo = github_repository.split("/", 1)
    return f"https://github.com/{owner}/{repo}"


def build_feed_url(github_repository: str, category_id: str) -> str:
    """Return the canonical GitHub Pages URL of the feed for the given owner/repo and category."""
    owner, repo = github_repository.split("/", 1)
    return (
        f"https://{owner}.github.io/{repo}/arxiv/{category_id.lower()}/atom.xml"
    )


def build_feed(
    articles: list[Article],
    category_id: str,
    strict_mode: bool,
    github_repository: str,
) -> bytes:
    """
    Build an Atom 1.0 feed (RFC 4287) from collected articles.

    Articles are sorted by published descending (newest first).
    The feed-level updated element is set to the published date of the first
    (newest) article so the value is stable across repeated runs with the same
    input data (NFR-005).

    Parameters:
      articles:          list of Article values as produced by parse_entries
                         and filtered by include_article
      category_id:       value of ARXIV_CATEGORY_ID (e.g. "cs.AI")
      strict_mode:       resolved value of ARXIV_CATEGORY_STRICT
      github_repository: value of GITHUB_REPOSITORY (format "owner/repo")

    Returns:
      UTF-8 encoded Atom XML bytes with an XML declaration.

    Raises:
      ValueError: when articles is empty. The caller must ensure at least one
                  article is present; passing an empty list produces a feed
                  without the required <feed><updated> element (RFC 4287 §4.1.1).
    """
    if not articles:
        raise ValueError("build_feed requires at least one article")
    # Primary sort: published descending (newest first).
    # Secondary sort: abstract_url descending to break ties when two articles
    # share the same published timestamp, giving a stable ordering regardless
    # of input order (NFR-005).
    sorted_articles = sorted(
        articles, key=lambda a: (a.published, a.abstract_url), reverse=True
    )

    feed_url = build_feed_url(github_repository, category_id)
    repo_url = build_github_repo_url(github_repository)

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")

    title_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}title")
    strict_str = str(strict_mode).lower()
    title_elem.text = f"{category_id} strict={strict_str} {github_repository}"

    id_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}id")
    id_elem.text = feed_url

    if sorted_articles:
        updated_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}updated")
        updated_elem.text = sorted_articles[0].published

    link_self_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    link_self_elem.set("rel", "self")
    link_self_elem.set("type", "application/atom+xml")
    link_self_elem.set("href", feed_url)

    link_alt_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    link_alt_elem.set("rel", "alternate")
    link_alt_elem.set("type", "text/html")
    link_alt_elem.set("href", repo_url)

    for article in sorted_articles:
        entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")

        title_e = ET.SubElement(entry, f"{{{_ATOM_NS}}}title")
        title_e.text = f"[{article.primary_category}] {article.title}"

        for author_name in article.authors:
            author_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}author")
            name_elem = ET.SubElement(author_elem, f"{{{_ATOM_NS}}}name")
            name_elem.text = author_name

        cat_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}category")
        cat_elem.set("term", article.primary_category)
        cat_elem.set("scheme", "http://arxiv.org/schemas/atom")

        id_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}id")
        id_elem.text = article.abstract_url

        link_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        link_elem.set("rel", "alternate")
        link_elem.set("type", "text/html")
        link_elem.set("href", article.abstract_url)

        pub_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}published")
        pub_elem.text = article.published

        upd_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}updated")
        upd_elem.text = article.updated

        # "et al." when three or more authors; both names when one or two.
        author_credit = (
            f"{article.authors[0]} et al."
            if len(article.authors) >= 3
            else ", ".join(article.authors)
        )
        content_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}content")
        content_elem.set("type", "html")
        # html.escape() HTML-encodes user text before ElementTree XML-serialises
        # the element; some feed readers collapse bare newlines and misinterpret
        # raw "&" or "<" in abstracts/comments as HTML markup.
        # <h3> headings make the section labels slightly larger than body text.
        content_elem.text = "\n".join([
            "<h3>Authors:</h3>",
            "<p>" + html.escape(author_credit) + "</p>",
            "<h3>Abstract:</h3>",
            "<p>" + html.escape(article.abstract) + "</p>",
            "<h3>Comments:</h3>",
            "<p>" + html.escape(article.comment or "") + "</p>",
        ])

    ET.indent(feed, space="  ")
    return ET.tostring(feed, encoding="UTF-8", xml_declaration=True)


def build_commit_message_from_bytes(feed_bytes: bytes) -> str:
    """
    Construct the commit message string from raw Atom feed bytes.

    Counts <entry> elements in feed_bytes, derives the ISO year and week from
    the newest <entry><published> date, and formats the message as:
    "Update YYYY-WNN feed (N article)" or "Update YYYY-WNN feed (N articles)".

    Callers must ensure feed_bytes contains at least one <entry>; passing a
    feed with no entries raises ValueError.
    """
    root = ET.fromstring(feed_bytes)
    n = len(root.findall(f"{{{_ATOM_NS}}}entry"))
    if n == 0:
        raise ValueError(
            "build_commit_message: feed contains no <entry> elements"
        )
    newest_date = newest_published_date_from_feed(feed_bytes)
    # n > 0 means at least one entry, but every entry may lack <published>;
    # build_feed always writes a <published> element, so this is unreachable
    # for feeds produced by this module.
    assert newest_date is not None, "feed has entries but no published dates"
    entry_date = _parse_rfc3339_utc_date(newest_date)
    iso = entry_date.isocalendar()
    week_str = f"{iso.year}-W{iso.week:02d}"
    article_word = "article" if n == 1 else "articles"
    return f"Update {week_str} feed ({n} {article_word})"


def build_commit_message(atom_xml_path: pathlib.Path) -> str:
    """Read the feed at atom_xml_path and return the commit message string."""
    return build_commit_message_from_bytes(atom_xml_path.read_bytes())


# ---------------------------------------------------------------------------
# Diff output
# ---------------------------------------------------------------------------


def print_unified_diff(
    prior_bytes: bytes, new_bytes: bytes, label: str
) -> None:
    """
    Compute a unified diff between prior_bytes and new_bytes and write it to
    stdout directly (not through the JSON logger) so that diff header lines
    appear as-is for human readers in the workflow log.

    label is used as both the fromfile and tofile argument of unified_diff
    (e.g. the output path string) so the +++ / --- headers identify the file.
    """
    prior_lines = prior_bytes.decode("utf-8").splitlines(keepends=True)
    new_lines = new_bytes.decode("utf-8").splitlines(keepends=True)
    sys.stdout.writelines(
        difflib.unified_diff(
            prior_lines, new_lines, fromfile=label, tofile=label
        )
    )
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Archive and staleness
# ---------------------------------------------------------------------------


def newest_published_date_from_feed(feed_bytes: bytes) -> str | None:
    """
    Parse an Atom feed and return the maximum <entry><published> date string.

    Compares dates as strings; RFC 3339 timestamps with the same format are
    lexicographically ordered, so max() gives the newest date without parsing.
    Returns None when the feed contains no <entry> elements with a published
    date.
    """
    root = ET.fromstring(feed_bytes)
    published_dates: list[str] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        published_elem = entry.find(f"{{{_ATOM_NS}}}published")
        if published_elem is not None and published_elem.text:
            published_dates.append(published_elem.text)
    if not published_dates:
        return None
    return max(published_dates)


def archive_prior_week_feed(
    output_path: pathlib.Path, today: datetime.date
) -> None:
    """
    Copy output_path to the archive directory when its newest entry belongs
    to a prior ISO week.

    The archive path is docs/arxiv/{category}/archive/YYYY-WNN/atom.xml where
    YYYY-WNN is the ISO year and week of the existing file's newest entry.
    Does nothing when output_path does not exist, the feed has no entries, or
    the newest entry is already in the current ISO week.
    """
    if not output_path.exists():
        return

    feed_bytes = output_path.read_bytes()
    newest_date = newest_published_date_from_feed(feed_bytes)
    if newest_date is None:
        return

    entry_date = _parse_rfc3339_utc_date(newest_date)
    entry_iso = entry_date.isocalendar()
    today_iso = today.isocalendar()

    if (entry_iso.year, entry_iso.week) == (today_iso.year, today_iso.week):
        return

    archive_week = f"{entry_iso.year}-W{entry_iso.week:02d}"
    archive_dir = output_path.parent / "archive" / archive_week
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_target = archive_dir / "atom.xml"
    _logger.info("archiving %s to %s", output_path, archive_target)
    archive_target.write_bytes(feed_bytes)


def find_latest_archive_path(archive_dir: pathlib.Path) -> pathlib.Path | None:
    """
    Return atom.xml under the lexicographically latest YYYY-WNN subdirectory.

    ISO 8601 week notation (zero-padded week number) makes lexicographic order
    equal to calendar order, so a simple sort is sufficient.  Returns None when
    archive_dir does not exist or contains no atom.xml files.
    """
    if not archive_dir.is_dir():
        return None
    week_dirs = sorted(d for d in archive_dir.iterdir() if d.is_dir())
    for week_dir in reversed(week_dirs):
        candidate = week_dir / "atom.xml"
        if candidate.exists():
            return candidate
    return None


def check_feed_staleness(
    atom_xml_path: pathlib.Path,
    today: datetime.date,
    max_staleness_days: int,
) -> int:
    """
    Log the feed age and return 1 when the newest entry is more than
    max_staleness_days calendar days old; return 0 otherwise.

    Always reads atom_xml_path (when it exists) and logs an INFO line with the
    feed age, today's date, and the threshold.  Returns 0 immediately after
    logging when max_staleness_days is -1 (check disabled).  Returns 0 when
    atom_xml_path does not exist or contains no <entry> elements with a
    <published> date.  Callers must validate max_staleness_days before calling:
    it must be -1 or a positive integer.

    Parameters:
      atom_xml_path:      path to the Atom feed file to check
      today:              reference date (UTC) for the staleness comparison
      max_staleness_days: -1 to disable; positive integer N means the feed is
                          considered stale when its newest entry is strictly
                          more than N calendar days old (age == N still passes)
    """
    if not atom_xml_path.exists():
        _logger.info("feed file not found: %s", atom_xml_path)
        return 0

    newest_date_str = newest_published_date_from_feed(atom_xml_path.read_bytes())
    if newest_date_str is None:
        _logger.info("feed has no entries: %s", atom_xml_path)
        return 0

    entry_date = _parse_rfc3339_utc_date(newest_date_str)
    delta_days = (today - entry_date).days
    threshold_str = (
        "disabled" if max_staleness_days == -1 else f"{max_staleness_days} days"
    )
    _logger.info(
        "feed age: %d days (newest entry: %s, today: %s, threshold: %s)",
        delta_days,
        entry_date,
        today,
        threshold_str,
    )

    if max_staleness_days == -1:
        return 0

    if delta_days > max_staleness_days:
        _logger.error(
            "feed is stale: newest entry %s is %d days old (threshold: %d days)",
            newest_date_str,
            delta_days,
            max_staleness_days,
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# Pagination and article fetching
# ---------------------------------------------------------------------------


def fetch_all_articles(
    base_url: str,
    category_id: str,
    today: datetime.date,
    backoff_base_seconds: float,
    max_results: int,
) -> list[Article]:
    """
    Fetch all arxiv articles for the ISO week that contains today, paginating
    in steps of max_results.

    NFR-002: sleeps _MIN_REQUEST_INTERVAL_SECONDS before every API request.
    FR-011: retries the first page up to max_retries_first_page times with exponential backoff on
    non-200 responses; exits immediately on non-200 for subsequent pages.

    Returns an empty list when the first API page returns HTTP 200 with zero
    entries; this is a valid result for the start of a new ISO week (Monday
    before arxiv has processed any submissions) or a quiet category.

    Raises RuntimeError on unrecoverable errors:
    - all retries for the first page exhausted
    - non-200 on a pagination page
    """
    monday, sunday = compute_week_bounds(today)
    max_retries_first_page = 3
    start = 0
    all_articles: list[Article] = []

    while True:
        url = build_api_url(
            base_url, category_id, monday, sunday, start, max_results
        )
        _logger.info("requesting %s", url)

        # NFR-002: pause before every request, including the first.
        time.sleep(_MIN_REQUEST_INTERVAL_SECONDS)

        if start == 0:
            status, body = _fetch_page(url)
            # Retry up to max_retries_first_page times on non-200.
            for retry_number in range(max_retries_first_page):
                if status == 200:
                    break
                wait_seconds = (retry_number + 1) * backoff_base_seconds
                _logger.info(
                    "retry %d of %d after HTTP %d: waiting %s s then re-requesting %s",
                    retry_number + 1, max_retries_first_page, status, wait_seconds, url,
                )
                time.sleep(wait_seconds)
                status, body = _fetch_page(url)

            if status != 200:
                raise RuntimeError(
                    f"First API page failed after {max_retries_first_page}"
                    f" retries: HTTP {status}"
                )
        else:
            # No retry for pagination pages (start > 0): the arxiv dataset is
            # live and the result window may shift between requests — articles
            # near page boundaries can be duplicated or silently dropped when
            # the underlying dataset changes between page fetches.  A safe
            # retry would require restarting from start=0, which this loop
            # does not implement.
            status, body = _fetch_page(url)
            if status != 200:
                raise RuntimeError(
                    f"Pagination request failed: HTTP {status} (start={start})"
                )

        try:
            articles = parse_entries(body)
        except ET.ParseError as exc:
            raise RuntimeError(
                f"Malformed XML in API response (start={start}): {exc}"
            ) from exc
        count = len(articles)
        _logger.info("Fetched %d results (start=%d)", count, start)

        all_articles.extend(articles)

        if count < max_results:
            # Received fewer entries than requested: this is the last page.
            break

        start += max_results

    return all_articles


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    """Configure root logger: INFO and below go to stdout, ERROR and above to stderr, both as UTC JSON."""
    formatter = _UtcJsonFormatter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(_is_not_error)
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(formatter)

    root = logging.getLogger()
    # Clear any previously installed handlers so repeated in-process calls
    # (e.g. from BDD step definitions invoking main() per scenario) do not
    # accumulate duplicate handlers that emit each log record N times after
    # N scenarios.  Also rebinds the handlers to the current sys.stdout /
    # sys.stderr, which matters when behave or contextlib.redirect_* has
    # swapped the streams between calls.
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)


def run_staleness_check(base_dir: pathlib.Path = pathlib.Path(".")) -> int:
    """
    Resolve staleness check parameters from the environment and run the check.

    Reads ARXIV_CATEGORY_ID, ARXIV_MAX_STALENESS_DAYS (default -1, disabled),
    and PIPELINE_TODAY (default: current UTC date) from the environment.
    The feed file is resolved as base_dir / "docs" / "arxiv" / {category} /
    "atom.xml"; callers that run in a different working directory pass base_dir
    explicitly instead of relying on the process cwd.

    Returns 0 on success or when the check is disabled; returns 1 on invalid
    configuration or when the feed is stale.

    Parameters:
      base_dir: root of the docs/ tree; defaults to the current working directory
    """
    _setup_logging()

    try:
        category_id = resolve_category_id()
    except ValueError as exc:
        _logger.error("%s", exc)
        return 1

    max_staleness_days_str = os.environ.get("ARXIV_MAX_STALENESS_DAYS", "-1")
    try:
        max_staleness_days = _validate_staleness_days(max_staleness_days_str)
    except ValueError as exc:
        _logger.error("%s", exc)
        return 1

    today = _resolve_today()
    feed_path = base_dir / "docs" / "arxiv" / category_id.lower() / "atom.xml"

    return check_feed_staleness(feed_path, today, max_staleness_days)


def main(base_dir: pathlib.Path = pathlib.Path(".")) -> int:
    """
    Run the pipeline and return the process exit code.

    The docs/ tree is resolved relative to base_dir so callers that run in a
    different working directory (e.g. BDD step definitions invoking main()
    in-process against a temporary directory) pass base_dir explicitly
    rather than relying on the process cwd.  The default keeps the existing
    behaviour for the shell script entry point.
    """
    _setup_logging()

    github_repository = os.environ.get("GITHUB_REPOSITORY")
    if not github_repository:
        _logger.error("GITHUB_REPOSITORY is not set")
        return 1

    base_url = os.environ.get("ARXIV_API_BASE_URL", "https://export.arxiv.org")
    category_id = resolve_category_id()
    strict_mode = resolve_strict_mode()
    backoff_base_seconds = float(
        os.environ.get("RETRY_BACKOFF_BASE_SECONDS", "60")
    )
    max_results = int(os.environ.get("ARXIV_MAX_RESULTS", "50"))
    today = _resolve_today()

    _logger.info(
        "pipeline starting: category=%s strict=%s today=%s",
        category_id, strict_mode, today,
    )

    continue_on_api_error = resolve_continue_on_api_error()

    try:
        articles = fetch_all_articles(
            base_url, category_id, today, backoff_base_seconds, max_results
        )
    except RuntimeError as exc:
        if continue_on_api_error:
            _logger.info("API failure, skipping feed update: %s", exc)
            return 0
        _logger.error("%s", exc)
        return 1

    _logger.info("fetched %d articles total", len(articles))

    if len(articles) == 0:
        _logger.info("no articles returned by the API for this period")
        return 0

    articles = [
        a for a in articles if matches_category(a, category_id, strict_mode)
    ]
    enriched = [enrich_from_metadata(a) for a in articles]
    filtered = [a for a in enriched if include_article(a)]
    n_filtered = len(filtered)
    article_word = "article" if n_filtered == 1 else "articles"
    _logger.info("%d %s passed the filter", n_filtered, article_word)

    if n_filtered == 0:
        _logger.info("no articles passed the inclusion filter for this period")
        return 0

    category_lower = category_id.lower()
    output_dir = base_dir / "docs" / "arxiv" / category_lower
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "atom.xml"

    # Capture the current file bytes before any changes for change detection.
    prior_bytes = output_path.read_bytes() if output_path.exists() else None

    archive_prior_week_feed(output_path, today)
    feed_bytes = build_feed(filtered, category_id, strict_mode, github_repository)

    # FR-013: unified diff between prior and newly generated feed for
    # diagnostic visibility in the workflow log.
    if prior_bytes is not None:
        print_unified_diff(prior_bytes, feed_bytes, str(output_path))

    if prior_bytes is not None and prior_bytes == feed_bytes:
        _logger.info("no change: feed unchanged")
    else:
        _logger.info("writing %s", output_path)
        output_path.write_bytes(feed_bytes)
        _logger.info(
            "%s",
            build_commit_message_from_bytes(feed_bytes),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
