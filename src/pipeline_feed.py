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
import json
import logging
import os
import pathlib
import re
import sys
import time
import typing
import urllib.error
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

_logger = logging.getLogger(__name__)


class Article(typing.NamedTuple):
    """One arxiv article: the fields extracted from the API response and consumed by the feed builder.

    authors and comment_urls are list[str] rather than tuple[str, ...] so that
    test code can compare them against literal lists with the == operator.
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
# Article inclusion filter
# ---------------------------------------------------------------------------


def include_article(
    article: Article, category_id: str, strict_mode: bool
) -> bool:
    """
    Return True if the article should be included in the feed.

    Both conditions must hold:
    1. Category condition: when strict_mode is True, article.primary_category
       must match category_id (case-insensitive); when strict_mode is False,
       any primary category is accepted.
    2. Comment URL condition: article.comment must contain at least one
       https:// URL; absent or empty comment fields are treated as no URL.

    Resolved values for category_id and strict_mode are passed in by the
    caller so the resolver is invoked once per pipeline run rather than once
    per article.

    Parameters:
      article:      the candidate article
      category_id:  resolved value of ARXIV_CATEGORY_ID (e.g. "cs.AI")
      strict_mode:  resolved value of ARXIV_CATEGORY_STRICT
    """
    if strict_mode and article.primary_category.lower() != category_id.lower():
        _logger.info(
            "rejected (strict category mismatch): primary=%s expected=%s"
            " published=%s title=%s url=%s",
            article.primary_category, category_id, article.published,
            article.title, article.abstract_url,
        )
        return False

    if not article.comment:
        _logger.info(
            "rejected (no comment): primary=%s published=%s title=%s url=%s",
            article.primary_category, article.published, article.title,
            article.abstract_url,
        )
        return False

    if not article.comment_urls:
        _logger.info(
            "rejected (no comment URL): primary=%s published=%s title=%s url=%s",
            article.primary_category, article.published, article.title,
            article.abstract_url,
        )
        return False

    _logger.info(
        "included: primary=%s published=%s title=%s url=%s",
        article.primary_category, article.published, article.title,
        article.abstract_url,
    )
    return True


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
        content_elem.set("type", "text")
        content_elem.text = "\n".join([
            "Authors:",
            author_credit,
            "",
            "Abstract:",
            article.abstract,
            "",
            "Comments:",
            article.comment or "",
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

    filtered = [
        article
        for article in articles
        if include_article(article, category_id, strict_mode)
    ]
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
