"""
Pipeline entry point: fetch arxiv articles for the current ISO week and write
docs/arxiv/{category}/atom.xml.

Environment variables read by this module:
  ARXIV_API_BASE_URL         optional; default "https://export.arxiv.org"
  ARXIV_CATEGORY_ID          optional; default "cs.AI"
  ARXIV_CATEGORY_STRICT      optional; "true" enables strict primary-category filter
  ARXIV_MAX_RESULTS          optional; entries per API page; default 100
  GITHUB_REPOSITORY          required; "owner/repo" (always set by GitHub Actions)
  PIPELINE_TODAY             optional; ISO date (YYYY-MM-DD) overrides the current UTC date
  RETRY_BACKOFF_BASE_SECONDS optional; seconds for exponential retry backoff; default 10
"""

import datetime
import json
import logging
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import src.utils

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

# Register the Atom namespace as the default so the serialiser writes
# <feed xmlns="..."> rather than <ns0:feed xmlns:ns0="...">.
ET.register_namespace("", _ATOM_NS)

# NFR-002: minimum pause before every API request to respect arxiv rate limits.
_MIN_REQUEST_INTERVAL_SECONDS: int = 5

# Characters stripped from the trailing end of each extracted comment URL.
# These are common punctuation characters that surround URLs in prose text.
_TRAILING_PUNCT: frozenset[str] = frozenset(".,;:)]>")

_logger = logging.getLogger(__name__)


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
    https://example.com/x.").  Returns an empty list when comment is None
    or empty.
    """
    if not comment:
        return []
    urls = re.findall(r"https://\S+", comment)
    result: list[str] = []
    for url in urls:
        while url and url[-1] in _TRAILING_PUNCT:
            url = url[:-1]
        result.append(url)
    return result


def parse_entries(body: bytes) -> list[dict]:
    """
    Parse an arxiv Atom XML response and return one dict per <entry>.

    Each dict contains:
      title:            str        atom:title text
      authors:          list[str]  atom:author/atom:name texts in document order
      primary_category: str        arxiv:primary_category term attribute value
      abstract_url:     str        atom:link[@rel='alternate'][@type='text/html'] href
      published:        str        atom:published text (RFC 3339)
      updated:          str        atom:updated text (RFC 3339)
      comment:          str | None arxiv:comment text, or None when absent
      comment_urls:     list[str]  https:// URLs from comment, punctuation stripped
    """
    root = ET.fromstring(body)
    entries = []
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

        comment_elem = entry.find(f"{{{_ARXIV_NS}}}comment")
        comment: str | None = (
            comment_elem.text if comment_elem is not None else None
        )

        entries.append(
            {
                "title": title,
                "authors": authors,
                "primary_category": primary_category,
                "abstract_url": abstract_url,
                "published": published,
                "updated": updated,
                "comment": comment,
                "comment_urls": extract_comment_urls(comment),
            }
        )
    return entries


def build_github_repo_url(github_repository: str) -> str:
    """
    Construct the GitHub repository URL from GITHUB_REPOSITORY.

    Parameters:
      github_repository: "owner/repo" as set by GITHUB_REPOSITORY

    Returns:
      https://github.com/{owner}/{repo}
    """
    owner, repo = github_repository.split("/", 1)
    return f"https://github.com/{owner}/{repo}"


def build_feed_url(github_repository: str, category_id: str) -> str:
    """
    Construct the canonical GitHub Pages URL for the feed.

    Splits github_repository on '/' to extract owner and repo, lowercases
    category_id for the URL path segment, and returns the full feed URL.

    Parameters:
      github_repository: "owner/repo" as set by GITHUB_REPOSITORY
      category_id:       ARXIV_CATEGORY_ID (e.g. "cs.AI")

    Returns:
      https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml
    """
    owner, repo = github_repository.split("/", 1)
    category_lower = category_id.lower()
    return f"https://{owner}.github.io/{repo}/arxiv/{category_lower}/atom.xml"


def build_feed(
    articles: list[dict],
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
      articles:          list of article dicts as returned by parse_entries and
                         filtered by include_article
      category_id:       value of ARXIV_CATEGORY_ID (e.g. "cs.AI")
      strict_mode:       resolved value of ARXIV_CATEGORY_STRICT
      github_repository: value of GITHUB_REPOSITORY (format "owner/repo")

    Returns:
      UTF-8 encoded Atom XML bytes with an XML declaration.
    """
    sorted_articles = sorted(
        articles, key=lambda a: a["published"], reverse=True
    )

    feed = ET.Element(f"{{{_ATOM_NS}}}feed")

    title_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}title")
    strict_str = str(strict_mode).lower()
    title_elem.text = f"{category_id} strict={strict_str} {github_repository}"

    feed_url = build_feed_url(github_repository, category_id)
    id_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}id")
    id_elem.text = feed_url

    if sorted_articles:
        updated_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}updated")
        updated_elem.text = sorted_articles[0]["published"]

    link_self_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    link_self_elem.set("rel", "self")
    link_self_elem.set("href", feed_url)

    link_alt_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}link")
    link_alt_elem.set("rel", "alternate")
    link_alt_elem.set("href", build_github_repo_url(github_repository))

    for article in sorted_articles:
        entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")

        title_e = ET.SubElement(entry, f"{{{_ATOM_NS}}}title")
        title_e.text = f"[{article['primary_category']}] {article['title']}"

        for author_name in article["authors"]:
            author_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}author")
            name_elem = ET.SubElement(author_elem, f"{{{_ATOM_NS}}}name")
            name_elem.text = author_name

        cat_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}category")
        cat_elem.set("term", article["primary_category"])
        cat_elem.set("scheme", "http://arxiv.org/schemas/atom")

        id_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}id")
        id_elem.text = article["abstract_url"]

        link_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        link_elem.set("rel", "alternate")
        link_elem.set("type", "text/html")
        link_elem.set("href", article["abstract_url"])

        pub_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}published")
        pub_elem.text = article["published"]

        upd_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}updated")
        upd_elem.text = article["updated"]

        content_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}content")
        content_elem.set("type", "text")
        content_elem.text = "\n".join(article["comment_urls"])

    ET.indent(feed, space="  ")
    return ET.tostring(feed, encoding="UTF-8", xml_declaration=True)


def newest_published_date_from_feed(feed_bytes: bytes) -> str | None:
    """
    Parse an Atom feed and return the maximum <entry><published> date string.

    Compares dates as strings; RFC 3339 timestamps with the same format are
    lexicographically ordered, so max() gives the newest date without parsing.
    Returns None when the feed contains no <entry> elements.
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

    # Parse the full RFC 3339 timestamp as a timezone-aware datetime and
    # convert to UTC before extracting the date.  fromisoformat handles the
    # "Z" UTC suffix in Python 3.11+.
    entry_dt = datetime.datetime.fromisoformat(newest_date)
    entry_date = entry_dt.astimezone(datetime.timezone.utc).date()
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


def fetch_all_articles(
    base_url: str,
    category_id: str,
    today: datetime.date,
    backoff_base_seconds: int,
    max_results: int,
) -> list[dict]:
    """
    Fetch all arxiv articles for the ISO week that contains today, paginating
    in steps of max_results.

    NFR-002: sleeps _MIN_REQUEST_INTERVAL_SECONDS before every API request.
    FR-011: retries the first page up to 2 times with exponential backoff on
    non-200 responses; exits immediately on non-200 for subsequent pages.

    Raises RuntimeError on unrecoverable errors:
    - all retries for the first page exhausted
    - non-200 on a pagination page
    - zero results returned by the first page (signals an API issue)
    """
    monday, sunday = compute_week_bounds(today)
    max_retries_first_page = 2
    start = 0
    all_entries: list[dict] = []

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

        entries = parse_entries(body)
        count = len(entries)
        _logger.info("fetched %d results (start=%d)", count, start)

        if start == 0 and count == 0:
            # Zero results on the first page signals an API issue, not an
            # empty week; the next daily run will retry the full week range.
            raise RuntimeError(
                "First API page returned zero entries; aborting to avoid"
                " publishing an empty feed"
            )

        all_entries.extend(entries)

        if count < max_results:
            # Received fewer entries than requested: this is the last page.
            break

        start += max_results

    return all_entries


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
    root.setLevel(logging.INFO)
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)


def main() -> int:
    """Run the pipeline and return the process exit code."""
    _setup_logging()

    github_repository = os.environ.get("GITHUB_REPOSITORY")
    if not github_repository:
        _logger.error("GITHUB_REPOSITORY is not set")
        return 1

    base_url = os.environ.get("ARXIV_API_BASE_URL", "https://export.arxiv.org")
    category_id = src.utils.resolve_category_id()
    strict_mode = src.utils.resolve_strict_mode()
    backoff_base_seconds = int(
        os.environ.get("RETRY_BACKOFF_BASE_SECONDS", "10")
    )
    max_results = int(os.environ.get("ARXIV_MAX_RESULTS", "100"))

    today_override = os.environ.get("PIPELINE_TODAY")
    today: datetime.date
    if today_override:
        today = datetime.date.fromisoformat(today_override)
    else:
        today = datetime.datetime.now(datetime.timezone.utc).date()

    _logger.info(
        "pipeline starting: category=%s strict=%s today=%s",
        category_id, strict_mode, today,
    )

    try:
        articles = fetch_all_articles(
            base_url, category_id, today, backoff_base_seconds, max_results
        )
    except RuntimeError as exc:
        _logger.error("%s", exc)
        return 1

    _logger.info("fetched %d articles total", len(articles))

    filtered = [
        article
        for article in articles
        if src.utils.include_article(
            article["primary_category"],
            article["comment"],
            abstract_url=article["abstract_url"],
            published=article["published"],
            title=article["title"],
        )
    ]
    n_filtered = len(filtered)
    article_word = "article" if n_filtered == 1 else "articles"
    _logger.info("%d %s passed the filter", n_filtered, article_word)

    if n_filtered == 0:
        _logger.error("no articles passed the inclusion filter; aborting")
        return 1

    category_lower = category_id.lower()
    output_dir = pathlib.Path("docs") / "arxiv" / category_lower
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "atom.xml"

    # Capture the current file bytes before any changes for change detection.
    prior_bytes = output_path.read_bytes() if output_path.exists() else None

    archive_prior_week_feed(output_path, today)
    feed_bytes = build_feed(filtered, category_id, strict_mode, github_repository)

    if prior_bytes is not None and prior_bytes == feed_bytes:
        _logger.info("no change: feed unchanged")
    else:
        _logger.info("writing %s", output_path)
        output_path.write_bytes(feed_bytes)
        _logger.info(
            "%s",
            src.utils.build_commit_message_from_bytes(feed_bytes),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
