"""
Pipeline entry point: fetch arxiv articles for the rolling window
[today - ARXIV_MAX_BACKFILL_DAYS, today], apply the inclusion filter,
and write docs/arxiv/{category}/atom.xml.

Environment variables read by this module:
  ARXIV_API_BASE_URL           optional; default "https://export.arxiv.org"
  ARXIV_CATEGORY_ID            optional; default "cs.AI"
  ARXIV_CATEGORY_STRICT        optional; "true" enables strict primary-category filter
  ARXIV_CONTINUE_ON_API_ERROR  optional; "true" exits 0 on API failure instead of 1
  ARXIV_MAX_BACKFILL_DAYS      optional; rolling window in days; default 8
  ARXIV_MAX_RESULTS            optional; entries per API page; default 50
  ARXIV_MAX_STALENESS_DAYS     optional; days before feed is considered stale; default -1 (disabled)
  GITHUB_REPOSITORY            required; "owner/repo" (always set by GitHub Actions)
  PIPELINE_TODAY               optional; ISO date (YYYY-MM-DD) overrides the current UTC date
  RETRY_BACKOFF_BASE_SECONDS   optional; seconds for exponential retry backoff; default 60
"""

import concurrent.futures
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
_CAF_NS = "tag:code-available-feed.github.io,2026:atom-extensions"

# Register the Atom namespace as the default so the serialiser writes
# <feed xmlns="..."> rather than <ns0:feed xmlns:ns0="...">.
ET.register_namespace("", _ATOM_NS)
ET.register_namespace("code-available-feed", _CAF_NS)

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

# Matches markdown link syntax where the link text is itself the same URL as
# the target, e.g. "[https://x](https://x)" -- a pattern some arxiv abstracts
# render literally with no whitespace between the two occurrences.  Without
# this collapse step, the greedy URL-matching regexes below treat the two
# occurrences as one run and merge them into a single garbled candidate.
# The backreference (\1) requires an exact match between the two URLs, so
# this never touches an ordinary markdown link with descriptive text (e.g.
# "[Project Page](https://x)") or a URL that legitimately embeds another URL
# as a query parameter (e.g. an OAuth-style redirect link), since neither
# contains two identical URLs framed by "[...](...)" .
_MARKDOWN_DUPLICATE_URL_PATTERN = re.compile(r"\[(https?://[^\]\s]+)\]\(\1\)")

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


class ProcessedEntry(typing.NamedTuple):
    """Stored cascade outcome for one article, persisted in the processed element.

    published is the arxiv <published> date (v1 submission date); it is stored
    so that status=aged_out log lines can show it alongside updated, making
    the submittedDate vs updated discrepancy visible in the log output.
    """

    published: str
    updated: str
    repo_found_in: str
    repo_urls: tuple[str, ...]


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
    """Return True when url's hostname matches any accepted domain or suffix.

    Raises ValueError when url is not parseable by urllib.parse.urlparse
    (e.g. a netloc starting with "[" that is not a valid IPv6 literal); this
    can happen for a candidate malformed by the regex passes in
    _extract_candidate_urls.  Callers must catch ValueError rather than
    treating every candidate as parseable.
    """
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in accepted_domains:
        return True
    return any(hostname.endswith(suffix) for suffix in accepted_suffixes)


def _extract_url_context(
    text: str,
    url: str,
    n_before: int = 10,
    n_after: int = 3,
) -> str:
    """Return up to n_before tokens before and n_after tokens after url in text.

    Splits text on whitespace and scans for a token whose content (after
    stripping trailing punctuation .,;:)]>) matches url with or without the
    https:// scheme prefix, to handle bare-domain matches.  A leading digit
    sequence directly prepended to "https://" (PDF footnote markers such as
    "2https://...") is also stripped before comparison so those tokens match.
    Adjacent URL tokens are included as-is so that a run of URLs is visible
    as a signal.  Semicolons are stripped from the result so callers can
    safely join multiple contexts with '; '.  Returns an empty string when url
    is not found.
    """
    url_bare = url[len("https://"):] if url.startswith("https://") else url
    tokens = text.split()
    for i, token in enumerate(tokens):
        stripped = token.rstrip(".,;:)]>")
        # PDF typesetters sometimes concatenate a footnote digit directly with
        # the https:// scheme (e.g. "2https://example.com").  Strip the leading
        # digit sequence before the scheme so such tokens still match the URL.
        stripped_no_footnote = re.sub(r"^[0-9]+(?=https://)", "", stripped)
        if stripped == url or stripped == url_bare or stripped_no_footnote == url:
            before = tokens[max(0, i - n_before):i]
            after = tokens[i + 1:min(len(tokens), i + 1 + n_after)]
            return " ".join(before + [token] + after).replace(";", "")
    return ""


def _extract_annotation_anchor(
    page: typing.Any,
    rect: tuple[float, float, float, float],
) -> str:
    """Return text within a /Link annotation bounding box using visitor_text.

    Calls page.extract_text(visitor_text=...) and keeps only text whose
    rendering position (text-matrix coordinates tm[4], tm[5]) falls within the
    annotation /Rect (PDF default user space, origin bottom-left).  A 1-point
    tolerance is applied to each boundary to absorb floating-point rounding.

    Returns the collected fragments joined by spaces, or an empty string when
    no text is found in the region.

    page must be a pypdf.PageObject; typed as Any because pypdf is imported
    inside extract_pdf_repo_urls rather than at module level.
    """
    x1, y1, x2, y2 = rect
    captured: list[str] = []

    def _visitor(
        text: str,
        cm: typing.Any,
        tm: typing.Any,
        fontdict: typing.Any,
        font_size: typing.Any,
    ) -> None:
        if not text.strip():
            return
        if tm is None or len(tm) < 6:
            return
        x, y = float(tm[4]), float(tm[5])
        if x1 - 1.0 <= x <= x2 + 1.0 and y1 - 1.0 <= y <= y2 + 1.0:
            captured.append(text.strip())

    page.extract_text(visitor_text=_visitor)
    return " ".join(t for t in captured if t)


def _extract_scheme_prefixed_candidates(text: str) -> list[str]:
    """Return raw https://-prefixed URL candidates found in text.

    Shared by _extract_candidate_urls (abstract/PDF, which also applies a
    bare-domain pass restricted to accepted domains) and extract_comment_urls
    (comment URLs accept any domain, so only this scheme-prefixed pass
    applies; there is no accepted-domain list to build a bare-domain regex
    from).  text is first passed through _MARKDOWN_DUPLICATE_URL_PATTERN so a
    markdown-style "[url](url)" duplicate collapses to one occurrence before
    the greedy https://[^\\s,]+ regex runs; without that collapse the two
    occurrences (separated by no whitespace) are matched as a single garbled
    run.  Trailing punctuation from the set .,;:)]> is stripped from each
    match.
    """
    collapsed = _MARKDOWN_DUPLICATE_URL_PATTERN.sub(r"\1", text)
    return [
        match.rstrip(".,;:)]>")
        for match in re.findall(r"https://[^\s,]+", collapsed)
    ]


def _extract_candidate_urls(
    text: str,
    accepted_domains: frozenset[str],
    accepted_suffixes: frozenset[str],
) -> list[str]:
    """Return raw (undeduplicated, unfiltered) URL candidates found in text.

    Shared by extract_repo_urls (whole abstract text) and
    extract_pdf_repo_urls (per-page PDF text).  Two regex passes are applied:
    1. _extract_scheme_prefixed_candidates captures scheme-prefixed URLs (see
       its docstring for the markdown-duplicate collapse it applies first).
    2. A bare-domain regex for each accepted domain and suffix captures URLs
       that appear without the https:// scheme (e.g. when LaTeX renders a
       URL via \\href{url}{icon}).  This pass also runs against the
       markdown-collapsed text, and skips any match that itself contains
       "://": a schemeless bare-domain match can never legitimately contain a
       scheme, so one that does means its greedy \\S+ prefix swallowed a
       preceding scheme-prefixed URL with no separating whitespace; that URL
       was already captured correctly by pass 1, so the match is spurious.

    Callers are responsible for deduplication and for filtering results to
    the accepted domain set via _is_url_on_accepted_domain.
    """
    candidates = _extract_scheme_prefixed_candidates(text)

    collapsed = _MARKDOWN_DUPLICATE_URL_PATTERN.sub(r"\1", text)
    bare_parts: list[str] = []
    for domain in sorted(accepted_domains):
        bare_parts.append(re.escape(domain))
    for suffix in sorted(accepted_suffixes):
        bare_parts.append(r"\S+" + re.escape(suffix))
    if bare_parts:
        bare_regex = f"(?:{'|'.join(bare_parts)})/\\S+"
        for match in re.findall(bare_regex, collapsed):
            if "://" in match:
                continue
            candidates.append(f"https://{match.rstrip('.,;:)]>')}")

    return candidates


def extract_repo_urls(
    text: str,
    accepted_domains: frozenset[str] | None = None,
    accepted_suffixes: frozenset[str] | None = None,
    source_url: str = "",
) -> list[str]:
    """Extract accepted-domain URLs from free-form text (abstract or PDF).

    See _extract_candidate_urls for the two regex passes applied.
    Results are deduplicated and filtered to the accepted domain set.  A
    candidate that _is_url_on_accepted_domain cannot parse (e.g. a
    scheme-prefixed URL malformed by the regex passes, see
    _extract_candidate_urls) is logged at INFO with status=abstract_malformed_url
    and excluded, rather than raising; source_url identifies the originating
    article in that log line and defaults to "" for direct/test callers that
    have no article context.
    """
    if not text:
        return []

    domains = accepted_domains if accepted_domains is not None else ACCEPTED_REPO_DOMAINS
    suffixes = accepted_suffixes if accepted_suffixes is not None else ACCEPTED_REPO_DOMAIN_SUFFIXES

    raw_urls = _extract_candidate_urls(text, domains, suffixes)

    seen: set[str] = set()
    filtered: list[str] = []
    for url in raw_urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            is_accepted = _is_url_on_accepted_domain(url, domains, suffixes)
        except ValueError:
            _logger.info(
                "origin=new status=abstract_malformed_url candidate=%s url=%s",
                url, source_url,
            )
            continue
        if is_accepted:
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
        urls = sorted(set(article.comment_urls))
        contexts = [_extract_url_context(article.comment or "", url) for url in urls]
        repo_context = "; ".join(c for c in contexts if c)
        repo_context_str = f'"{repo_context}"' if repo_context else ""
        _logger.info(
            "origin=new status=comment repo_found_in=comment repo_urls=%s repo_context=%s url=%s",
            ";".join(urls), repo_context_str, article.abstract_url,
        )
        return article._replace(
            repo_found_in="comment",
            repo_urls=tuple(urls),
        )
    _logger.info(
        "origin=new status=comment repo_found_in= repo_urls= repo_context= url=%s",
        article.abstract_url,
    )

    abstract_urls = extract_repo_urls(
        article.abstract,
        accepted_domains=accepted_domains,
        accepted_suffixes=accepted_suffixes,
        source_url=article.abstract_url,
    )
    if abstract_urls:
        urls = sorted(set(abstract_urls))
        contexts = [_extract_url_context(article.abstract, url) for url in urls]
        repo_context = "; ".join(c for c in contexts if c)
        repo_context_str = f'"{repo_context}"' if repo_context else ""
        _logger.info(
            "origin=new status=abstract repo_found_in=abstract repo_urls=%s repo_context=%s url=%s",
            ";".join(urls), repo_context_str, article.abstract_url,
        )
        return article._replace(
            repo_found_in="abstract",
            repo_urls=tuple(urls),
        )
    _logger.info(
        "origin=new status=abstract repo_found_in= repo_urls= repo_context= url=%s",
        article.abstract_url,
    )

    return article


def extract_pdf_repo_urls(
    pdf_bytes: bytes,
    max_pages: int = 10,
    accepted_domains: frozenset[str] | None = None,
    accepted_suffixes: frozenset[str] | None = None,
    source_url: str = "",
) -> tuple[list[str], list[str]]:
    """Extract accepted-domain URLs from PDF pages, stopping before References.

    Three extraction layers per page, applied in order:
    1. Link annotations (/Link with /A /URI) -- most reliable, full URIs
       from PDF hyperlink metadata.
    2. Text https://\\S+ regex -- catches scheme-prefixed visible URLs.
    3. Text bare domain regex -- catches URLs without https:// scheme
       (e.g. when LaTeX renders \\href{url}{icon}).

    Scanning stops when a page contains a standalone "References" or
    "REFERENCES" line; that page and all subsequent pages are skipped.

    A candidate (from any of the three layers) that _is_url_on_accepted_domain
    cannot parse is logged at INFO with status=pdf_malformed_url and excluded,
    rather than raising; source_url identifies the originating article in
    that log line and defaults to "" for direct/test callers that have no
    article context.

    Returns a tuple (urls, contexts):
      urls:     sorted, deduplicated, domain-filtered URLs.
      contexts: parallel list; contexts[i] is "pN: surrounding text" for
                urls[i], or an empty string when no surrounding text was found.
                Callers join non-empty entries with "; " to build repo_context.
    """
    import pypdf

    domains = accepted_domains if accepted_domains is not None else ACCEPTED_REPO_DOMAINS
    suffixes = accepted_suffixes if accepted_suffixes is not None else ACCEPTED_REPO_DOMAIN_SUFFIXES

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    raw_urls: list[str] = []
    # Maps each URL to its first-occurrence context string "pN: text".
    # An empty string means the URL was found but no surrounding text was extractable.
    url_context: dict[str, str] = {}

    for page_index in range(min(len(reader.pages), max_pages)):
        page = reader.pages[page_index]
        text = page.extract_text() or ""

        if re.search(r"(?m)^\s*(?:References|REFERENCES)\s*$", text):
            break

        page_raw: list[str] = []
        # Maps annotation-sourced URL to its /Rect for anchor text fallback
        # when _extract_url_context cannot find the URL in the page text.
        annotation_rects: dict[str, tuple[float, float, float, float]] = {}

        if page.annotations:
            for annotation in page.annotations:
                annotation_obj = annotation.get_object()
                if annotation_obj.get("/Subtype") == "/Link":
                    action = annotation_obj.get("/A")
                    if action:
                        uri = action.get("/URI")
                        if uri:
                            url_str = str(uri)
                            page_raw.append(url_str)
                            rect = annotation_obj.get("/Rect")
                            if rect is not None and len(rect) == 4:
                                annotation_rects[url_str] = tuple(
                                    float(v) for v in rect
                                )  # type: ignore[assignment]

        page_raw.extend(_extract_candidate_urls(text, domains, suffixes))

        page_accepted: list[str] = []
        for u in page_raw:
            try:
                is_accepted = _is_url_on_accepted_domain(u, domains, suffixes)
            except ValueError:
                _logger.info(
                    "origin=new status=pdf_malformed_url page=%d candidate=%s url=%s",
                    page_index + 1, u, source_url,
                )
                continue
            if is_accepted:
                page_accepted.append(u)

        for url in page_accepted:
            if url in url_context:
                continue
            ctx = _extract_url_context(text, url)
            if not ctx and url in annotation_rects:
                ctx = _extract_annotation_anchor(page, annotation_rects[url])
            url_context[url] = f"p{page_index + 1}: {ctx}" if ctx else ""

        raw_urls.extend(page_raw)

    # Deduplicate preserving first-occurrence order, then sort by URL so the
    # output is stable regardless of page order.
    seen: set[str] = set()
    url_ctx_pairs: list[tuple[str, str]] = []
    for url in raw_urls:
        if url in seen:
            continue
        seen.add(url)
        if _is_url_on_accepted_domain(url, domains, suffixes):
            url_ctx_pairs.append((url, url_context.get(url, "")))

    url_ctx_pairs.sort(key=lambda pair: pair[0])
    return [u for u, _ in url_ctx_pairs], [c for _, c in url_ctx_pairs]


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Return the number of pages in pdf_bytes.

    Called by enrich_from_pdf after downloading and before scanning so the
    page count is available for the status=pdf_fetched stats log line without
    a second full parse pass — pypdf.PdfReader is lightweight for page counting.
    """
    import pypdf
    return len(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


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
    _pdf_base_url: str = "https://export.arxiv.org",
) -> Article | None:
    """Enrich article with repo URLs extracted from its PDF body.

    Skips articles already enriched (repo_found_in is non-empty).
    Downloads the PDF from _pdf_base_url/pdf/{arxiv_id} and runs
    extract_pdf_repo_urls.  _pdf_base_url defaults to the production
    arxiv export server and is overridden in tests via the same
    ARXIV_API_BASE_URL mechanism used for API requests.
    Returns None on any error so the caller can exclude failed articles
    from the processed dict and retry them on the next run.
    """
    if article.repo_found_in:
        return article

    fetcher = _fetch_pdf if _fetch_pdf is not None else _default_fetch_pdf

    try:
        arxiv_id = article.abstract_url.rsplit("/", 1)[-1]
        pdf_url = f"{_pdf_base_url}/pdf/{arxiv_id}"
        _logger.info("origin=new status=pdf_fetching url=%s", article.abstract_url)
        t0 = time.monotonic()
        pdf_bytes = fetcher(pdf_url)
        download_s = time.monotonic() - t0
        n_pages = _count_pdf_pages(pdf_bytes)
        n_bytes = len(pdf_bytes)
        _logger.info(
            "origin=new status=pdf_fetched pages=%d bytes=%d download_s=%.1f url=%s",
            n_pages, n_bytes, download_s, article.abstract_url,
        )
        t1 = time.monotonic()
        urls, contexts = extract_pdf_repo_urls(
            pdf_bytes,
            accepted_domains=accepted_domains,
            accepted_suffixes=accepted_suffixes,
            source_url=article.abstract_url,
        )
        scan_s = time.monotonic() - t1
        repo_context = "; ".join(c for c in contexts if c)
        repo_context_str = f'"{repo_context}"' if repo_context else ""
        if urls:
            _logger.info(
                "origin=new status=pdf repo_found_in=pdf repo_urls=%s repo_context=%s"
                " scan_s=%.1f updated=%s url=%s",
                ";".join(urls), repo_context_str, scan_s,
                article.updated, article.abstract_url,
            )
            return article._replace(
                repo_found_in="pdf",
                repo_urls=tuple(sorted(set(urls))),
            )
        _logger.info(
            "origin=new status=pdf repo_found_in= repo_urls= repo_context="
            " scan_s=%.1f updated=%s url=%s",
            scan_s, article.updated, article.abstract_url,
        )
        return article
    except Exception as exc:
        _logger.info("origin=new status=pdf_error url=%s", article.abstract_url)
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


def include_article(article: Article, origin: str) -> bool:
    """Return True when the article has a code-availability URL from any cascade source.

    origin must be "new" or "cache" to identify where the article came from.
    The enrichment cascade (enrich_from_metadata or enrich_from_pdf) must
    have run before calling this function; it checks repo_found_in which is
    set by the cascade.
    status=rejected means all cascade stages completed and found no URL;
    pdf_failed articles must not pass through this function.
    """
    if article.repo_found_in:
        _logger.info(
            "origin=%s status=included repo_found_in=%s repo_urls=%s repo_context="
            " updated=%s title=%s url=%s",
            origin, article.repo_found_in, ";".join(sorted(article.repo_urls)),
            article.updated, f'"{article.title}"', article.abstract_url,
        )
        return True
    _logger.info(
        "origin=%s status=rejected repo_found_in= repo_urls= repo_context="
        " updated=%s title=%s url=%s",
        origin, article.updated, f'"{article.title}"', article.abstract_url,
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
    start_yyyymmdd: str,
    end_yyyymmdd: str,
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
        f"cat:{category_id}+AND+submittedDate:[{start_yyyymmdd}0000+TO+{end_yyyymmdd}2359]"
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


def extract_comment_urls(comment: str | None, source_url: str = "") -> list[str]:
    """
    Extract all https:// URLs from comment in order of appearance.

    Trailing characters from the set .,;:)]> are stripped from each URL to
    handle common punctuation that surrounds URLs in prose (e.g. "see
    https://example.com/x.").  Scheme-only results (bare "https://") that
    arise from stripping all content after the scheme — e.g. a comment
    containing "https://." — are excluded.  Comment URLs accept any domain
    (see FR-002), so unlike extract_repo_urls/extract_pdf_repo_urls there is
    no accepted-domain check here; a candidate is still validated by
    urllib.parse.urlparse to reject syntactically invalid URLs (e.g. a
    literal "[" immediately after the scheme).  A candidate that fails to
    parse is logged at INFO with status=comment_malformed_url and excluded,
    rather than raising; source_url identifies the originating article in
    that log line and defaults to "" for direct/test callers that have no
    article context.  Returns an empty list when comment is None or empty.
    """
    if not comment:
        return []

    urls: list[str] = []
    for url in _extract_scheme_prefixed_candidates(comment):
        if url == "https://":
            continue
        try:
            urllib.parse.urlparse(url)
        except ValueError:
            _logger.info(
                "origin=new status=comment_malformed_url candidate=%s url=%s",
                url, source_url,
            )
            continue
        urls.append(url)

    return urls


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
                comment_urls=extract_comment_urls(comment, source_url=abstract_url),
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
    processed: dict[str, ProcessedEntry],
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
      processed:         dict mapping abstract_url to ProcessedEntry; written
                         as a feed-level extension element
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

    feed.append(_build_processed_element(processed))

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
    if archive_target.exists():
        _logger.info("archive already exists, skipping: %s", archive_target)
        return
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
# Processed dict persistence
# ---------------------------------------------------------------------------


def load_processed(
    atom_xml_path: pathlib.Path,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> dict[str, ProcessedEntry]:
    """Load the processed dict from the extension element in atom.xml.

    Returns a dict keyed by article abstract_url.  When start_date and
    end_date are both provided, only entries whose updated date falls within
    [start_date, end_date] are kept.  When either is None, no date filter is
    applied and all entries in the processed element are returned.  Returns
    an empty dict when the file does not exist, the element is absent, or all
    entries are outside the window.

    Parameters:
      atom_xml_path: path to the Atom feed file
      start_date:    inclusive lower bound for the updated date filter;
                     None disables the filter
      end_date:      inclusive upper bound for the updated date filter;
                     None disables the filter
    """
    if not atom_xml_path.exists():
        return {}

    tree = ET.parse(atom_xml_path)
    root = tree.getroot()
    processed_elem = root.find(f"{{{_CAF_NS}}}processed")
    if processed_elem is None:
        return {}

    result: dict[str, ProcessedEntry] = {}
    for article_elem in processed_elem.findall(f"{{{_CAF_NS}}}article"):
        url = article_elem.get("url", "")
        published = article_elem.get("published", "")
        updated = article_elem.get("updated", "")
        repo_found_in = article_elem.get("repo_found_in", "")
        repo_urls_str = article_elem.get("repo_urls", "")
        repo_urls = tuple(u for u in repo_urls_str.split(";") if u) if repo_urls_str else ()

        if start_date is not None and end_date is not None:
            entry_date = _parse_rfc3339_utc_date(updated)
            if not (start_date <= entry_date <= end_date):
                continue

        result[url] = ProcessedEntry(
            published=published,
            updated=updated,
            repo_found_in=repo_found_in,
            repo_urls=repo_urls,
        )

    return result


def _build_processed_element(
    processed: dict[str, ProcessedEntry],
) -> ET.Element:
    """Build a <code-available-feed:processed> element from the dict."""
    processed_elem = ET.Element(f"{{{_CAF_NS}}}processed")
    for url in sorted(processed):
        entry = processed[url]
        article_elem = ET.SubElement(processed_elem, f"{{{_CAF_NS}}}article")
        article_elem.set("url", url)
        article_elem.set("published", entry.published)
        article_elem.set("updated", entry.updated)
        article_elem.set("repo_found_in", entry.repo_found_in)
        article_elem.set("repo_urls", ";".join(sorted(entry.repo_urls)))
    return processed_elem


def write_processed_element(
    atom_xml_path: pathlib.Path,
    processed: dict[str, ProcessedEntry],
) -> None:
    """Update the processed element in an existing atom.xml without touching entries.

    Does nothing when atom_xml_path does not exist.  Creates the processed
    element if absent, replaces it if present.  Entry elements are preserved
    unchanged.
    """
    if not atom_xml_path.exists():
        return

    tree = ET.parse(atom_xml_path)
    root = tree.getroot()

    existing = root.find(f"{{{_CAF_NS}}}processed")
    if existing is not None:
        root.remove(existing)

    new_elem = _build_processed_element(processed)
    root.append(new_elem)
    ET.indent(new_elem, space="  ", level=1)

    tree.write(atom_xml_path, encoding="UTF-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Pagination and article fetching
# ---------------------------------------------------------------------------


def fetch_all_articles(
    base_url: str,
    category_id: str,
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    backoff_base_seconds: float,
    max_results: int,
) -> list[Article]:
    """
    Fetch all arxiv articles for the rolling window [start_yyyymmdd, end_yyyymmdd],
    paginating in steps of max_results.

    NFR-002: sleeps _MIN_REQUEST_INTERVAL_SECONDS before every API request.
    FR-011: retries the first page up to max_retries_first_page times with exponential backoff on
    non-200 responses; exits immediately on non-200 for subsequent pages.

    Returns an empty list when the first API page returns HTTP 200 with zero
    entries; this is a valid result for a quiet period or a small category.

    Raises RuntimeError on unrecoverable errors:
    - all retries for the first page exhausted
    - non-200 on a pagination page
    """
    max_retries_first_page = 3
    start = 0
    all_articles: list[Article] = []

    while True:
        url = build_api_url(
            base_url, category_id, start_yyyymmdd, end_yyyymmdd, start, max_results
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
        _logger.info("fetched %d results (start=%d)", count, start)

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
    max_backfill_days = resolve_max_backfill_days()
    today = _resolve_today()
    start_date = today - datetime.timedelta(days=max_backfill_days)
    start_yyyymmdd = start_date.strftime("%Y%m%d")
    end_yyyymmdd = today.strftime("%Y%m%d")

    category_lower = category_id.lower()
    output_dir = base_dir / "docs" / "arxiv" / category_lower
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "atom.xml"

    archive_prior_week_feed(output_path, today)

    _logger.info(
        "pipeline starting: category=%s strict=%s today=%s backfill_days=%d",
        category_id, strict_mode, today, max_backfill_days,
    )

    continue_on_api_error = resolve_continue_on_api_error()

    try:
        articles = fetch_all_articles(
            base_url, category_id, start_yyyymmdd, end_yyyymmdd,
            backoff_base_seconds, max_results,
        )
    except RuntimeError as exc:
        if continue_on_api_error:
            _logger.info("API failure, skipping feed update: %s", exc)
            return 0
        _logger.error("%s", exc)
        return 1

    n_api_fetched = len(articles)

    if n_api_fetched == 0:
        _logger.info("no articles returned by the API for this period")
        return 0

    prior_processed_full = load_processed(output_path)
    processed = load_processed(output_path, start_date, today)
    n_aged_out = len(prior_processed_full) - len(processed)

    articles = [
        a for a in articles if matches_category(a, category_id, strict_mode)
    ]

    # Attach stored cascade outcomes to previously processed articles
    restored: list[Article] = []
    to_enrich: list[Article] = []
    for a in articles:
        if a.abstract_url in processed:
            entry = processed[a.abstract_url]
            _logger.info(
                "origin=cache status=cached repo_found_in=%s repo_urls=%s"
                " repo_context= published=%s updated=%s title=%s url=%s",
                entry.repo_found_in,
                ";".join(sorted(entry.repo_urls)),
                entry.published,
                entry.updated,
                f'"{a.title}"',
                a.abstract_url,
            )
            restored.append(a._replace(
                repo_found_in=entry.repo_found_in,
                repo_urls=entry.repo_urls,
            ))
        else:
            to_enrich.append(a)

    _logger.info(
        "%d articles fetched from the API, %d articles loaded from cache, "
        "%d aged out of the window, %d new to enrich",
        n_api_fetched, len(restored), n_aged_out, len(to_enrich),
    )

    enriched_meta = [enrich_from_metadata(a) for a in to_enrich]

    # Split: metadata found a URL, or needs PDF enrichment (FR-002 cascade step 3)
    meta_found = [a for a in enriched_meta if a.repo_found_in]
    needs_pdf = [a for a in enriched_meta if not a.repo_found_in]

    # PDF enrichment via thread pool (FR-016, max_workers=3 per REQUIREMENTS).
    # Uses ARXIV_API_BASE_URL so tests can redirect PDF requests to the fixture server.
    pdf_base_url = os.environ.get("ARXIV_API_BASE_URL", "https://export.arxiv.org")
    pdf_outcomes: list[Article | None] = []
    if needs_pdf:
        _logger.info("enriching %d articles from PDF", len(needs_pdf))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            pdf_outcomes = list(executor.map(
                lambda a: enrich_from_pdf(a, _pdf_base_url=pdf_base_url),
                needs_pdf,
            ))

    # Separate successfully attempted articles from failed PDF downloads.
    # None means the download failed; those articles are not added to the
    # processed dict so the download is retried on the next run.
    pdf_succeeded: list[Article] = []
    pdf_failed: list[Article] = []
    for orig, result in zip(needs_pdf, pdf_outcomes):
        if result is None:
            pdf_failed.append(orig)
        else:
            pdf_succeeded.append(result)

    if needs_pdf:
        _logger.info(
            "PDF enrichment done: %d with URL, %d without URL, %d failed (will retry)",
            sum(1 for a in pdf_succeeded if a.repo_found_in),
            sum(1 for a in pdf_succeeded if not a.repo_found_in),
            len(pdf_failed),
        )

    # Keep all_articles for delta-count computation (current_all_urls, n_failed_new).
    all_articles = restored + meta_found + pdf_succeeded + pdf_failed
    # pdf_failed articles already logged status=pdf_error inside enrich_from_pdf;
    # they must not reach include_article so status=rejected means only "cascade
    # completed and found no URL", never "PDF download failed".
    filtered = (
        [a for a in restored if include_article(a, origin="cache")]
        + [a for a in meta_found + pdf_succeeded if include_article(a, origin="new")]
    )
    n_filtered = len(filtered)
    n_failed_filter = len(all_articles) - n_filtered
    n_comment = sum(1 for a in filtered if a.repo_found_in == "comment")
    n_abstract = sum(1 for a in filtered if a.repo_found_in == "abstract")
    n_pdf = sum(1 for a in filtered if a.repo_found_in == "pdf")

    # Delta counts relative to the prior run's atom.xml state.
    # prior_processed_full has no date windowing, so aged-out entries and their
    # repo_found_in values are visible for the per-source breakdown.
    prior_filtered_urls = frozenset(
        url for url, e in prior_processed_full.items() if e.repo_found_in
    )
    prior_failed_urls = frozenset(
        url for url, e in prior_processed_full.items() if not e.repo_found_in
    )
    current_filtered_urls = frozenset(a.abstract_url for a in filtered)
    current_all_urls = frozenset(a.abstract_url for a in all_articles)
    aged_out_filtered_urls = prior_filtered_urls - current_filtered_urls
    for url in sorted(aged_out_filtered_urls):
        entry = prior_processed_full[url]
        # repo_context= is always empty here: context strings are not stored in
        # ProcessedEntry (adding them would require an atom.xml schema change).
        _logger.info(
            "origin=cache status=aged_out repo_found_in=%s repo_urls=%s"
            " repo_context= published=%s updated=%s url=%s",
            entry.repo_found_in,
            ";".join(sorted(entry.repo_urls)),
            entry.published,
            entry.updated,
            url,
        )
    n_filtered_aged_out = len(aged_out_filtered_urls)
    n_filtered_new = len(current_filtered_urls - prior_filtered_urls)
    n_comment_aged_out = sum(
        1 for u in aged_out_filtered_urls
        if prior_processed_full[u].repo_found_in == "comment"
    )
    n_abstract_aged_out = sum(
        1 for u in aged_out_filtered_urls
        if prior_processed_full[u].repo_found_in == "abstract"
    )
    n_pdf_aged_out = sum(
        1 for u in aged_out_filtered_urls
        if prior_processed_full[u].repo_found_in == "pdf"
    )
    n_comment_new = sum(
        1 for a in filtered
        if a.repo_found_in == "comment" and a.abstract_url not in prior_filtered_urls
    )
    n_abstract_new = sum(
        1 for a in filtered
        if a.repo_found_in == "abstract" and a.abstract_url not in prior_filtered_urls
    )
    n_pdf_new = sum(
        1 for a in filtered
        if a.repo_found_in == "pdf" and a.abstract_url not in prior_filtered_urls
    )
    # Failed aged-out: prior failing articles no longer in the current window.
    # Failed new: currently failing articles absent from the prior processed dict.
    n_failed_aged_out = len(prior_failed_urls - current_all_urls)
    n_failed_new = sum(
        1 for a in all_articles
        if not a.repo_found_in and a.abstract_url not in prior_processed_full
    )

    passed_word = "article" if n_filtered == 1 else "articles"
    failed_word = "article" if n_failed_filter == 1 else "articles"
    _logger.info(
        "%d %s (%d aged out of the window, %d new) passed the filter"
        " (comment: %d (%d, %d), abstract: %d (%d, %d), pdf: %d (%d, %d));"
        " %d (%d, %d) %s failed the filter",
        n_filtered, passed_word, n_filtered_aged_out, n_filtered_new,
        n_comment, n_comment_aged_out, n_comment_new,
        n_abstract, n_abstract_aged_out, n_abstract_new,
        n_pdf, n_pdf_aged_out, n_pdf_new,
        n_failed_filter, n_failed_aged_out, n_failed_new, failed_word,
    )

    # Build updated processed dict:
    # - meta_found: found via comment or abstract
    # - pdf_succeeded: PDF enrichment ran to completion (URL found or empty)
    # - pdf_failed: download failed; excluded so the download is retried next run
    new_processed = dict(processed)
    for a in meta_found + pdf_succeeded:
        new_processed[a.abstract_url] = ProcessedEntry(
            published=a.published,
            updated=a.updated,
            repo_found_in=a.repo_found_in,
            repo_urls=a.repo_urls,
        )
    new_processed = {
        url: entry for url, entry in new_processed.items()
        if start_date <= _parse_rfc3339_utc_date(entry.updated) <= today
    }

    if n_filtered == 0:
        _logger.info("no articles passed the inclusion filter for this period")
        write_processed_element(output_path, new_processed)
        return 0

    # Capture the current file bytes before any changes for change detection.
    prior_bytes = output_path.read_bytes() if output_path.exists() else None

    feed_bytes = build_feed(
        filtered, new_processed, category_id, strict_mode, github_repository,
    )

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
