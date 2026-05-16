"""
Pipeline entry point: fetch arxiv articles for the current ISO week and write
docs/arxiv/{category}/atom.xml.

Environment variables read by this module:
  GITHUB_REPOSITORY          required; "owner/repo" (always set by GitHub Actions)
  ARXIV_CATEGORY_ID          optional; default "cs.AI"
  ARXIV_CATEGORY_STRICT      optional; "true" enables strict primary-category filter
  ARXIV_API_BASE_URL         optional; default "https://export.arxiv.org"
  PIPELINE_TODAY             optional; ISO date (YYYY-MM-DD) overrides the current UTC date
  RETRY_BACKOFF_BASE_SECONDS optional; seconds for exponential retry backoff; default 10
"""

import datetime
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import src.config
import src.filter

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

    # RFC 3339 date strings start with YYYY-MM-DD; fromisoformat handles the
    # date portion without needing to strip the time and timezone suffix.
    entry_date = datetime.date.fromisoformat(newest_date[:10])
    entry_iso = entry_date.isocalendar()
    today_iso = today.isocalendar()

    if (entry_iso.year, entry_iso.week) == (today_iso.year, today_iso.week):
        return

    archive_week = f"{entry_iso.year}-W{entry_iso.week:02d}"
    archive_dir = output_path.parent / "archive" / archive_week
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "atom.xml").write_bytes(feed_bytes)


def feeds_are_identical(
    committed_bytes: bytes | None, generated_bytes: bytes
) -> bool:
    """
    Return True if committed_bytes equals generated_bytes.

    Returns False when committed_bytes is None, which indicates that no prior
    committed version exists (first pipeline run).
    """
    return committed_bytes is not None and committed_bytes == generated_bytes


def build_commit_message(feed_bytes: bytes) -> str:
    """
    Construct the git commit message for a weekly feed update.

    Counts <entry> elements in feed_bytes, derives the ISO year and week from
    the newest <entry><published> date, and formats the message as:
    "Update YYYY-WNN feed (N article)" or "Update YYYY-WNN feed (N articles)".

    Parameters:
      feed_bytes: UTF-8 encoded Atom XML bytes of the generated feed
    """
    root = ET.fromstring(feed_bytes)
    entries = root.findall(f"{{{_ATOM_NS}}}entry")
    n = len(entries)
    article_word = "article" if n == 1 else "articles"
    newest_date = newest_published_date_from_feed(feed_bytes)
    # newest_date is non-None here: build_commit_message is only called when
    # the feed contains at least one entry.
    entry_date = datetime.date.fromisoformat(newest_date[:10])
    iso = entry_date.isocalendar()
    week_str = f"{iso.year}-W{iso.week:02d}"
    return f"Update {week_str} feed ({n} {article_word})"


def fetch_all_articles(
    base_url: str,
    category_id: str,
    today: datetime.date,
    backoff_base_seconds: int,
) -> list[dict]:
    """
    Fetch all arxiv articles for the ISO week that contains today, paginating
    in steps of 2000.

    NFR-002: sleeps _MIN_REQUEST_INTERVAL_SECONDS before every API request.
    FR-011: retries the first page up to 2 times with exponential backoff on
    non-200 responses; exits immediately on non-200 for subsequent pages.

    Raises RuntimeError on unrecoverable errors:
    - all retries for the first page exhausted
    - non-200 on a pagination page
    - zero results returned by the first page (signals an API issue)
    """
    monday, sunday = compute_week_bounds(today)
    max_results = 2000
    max_retries_first_page = 2
    start = 0
    all_entries: list[dict] = []

    while True:
        url = build_api_url(
            base_url, category_id, monday, sunday, start, max_results
        )
        print(url, flush=True)

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
            # Pagination pages: no retry; a failure here means the session is
            # already partially complete and the error is unlikely transient.
            status, body = _fetch_page(url)
            if status != 200:
                raise RuntimeError(
                    f"Pagination request failed: HTTP {status} (start={start})"
                )

        entries = parse_entries(body)
        count = len(entries)
        print(f"Fetched {count} results (start={start})", flush=True)

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


def main() -> int:
    """Run the pipeline and return the process exit code."""
    github_repository = os.environ.get("GITHUB_REPOSITORY")
    if not github_repository:
        print(
            "Error: GITHUB_REPOSITORY is not set",
            file=sys.stderr,
            flush=True,
        )
        return 1

    category_id = src.config.resolve_category_id()
    strict_mode = src.config.resolve_strict_mode()
    base_url = os.environ.get("ARXIV_API_BASE_URL", "https://export.arxiv.org")
    backoff_base_seconds = int(
        os.environ.get("RETRY_BACKOFF_BASE_SECONDS", "10")
    )

    today_override = os.environ.get("PIPELINE_TODAY")
    today: datetime.date
    if today_override:
        today = datetime.date.fromisoformat(today_override)
    else:
        today = datetime.datetime.now(datetime.timezone.utc).date()

    try:
        articles = fetch_all_articles(
            base_url, category_id, today, backoff_base_seconds
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        return 1

    filtered = [
        article
        for article in articles
        if src.filter.include_article(
            article["primary_category"],
            article["comment"],
        )
    ]
    n_filtered = len(filtered)
    singular = n_filtered == 1
    print(
        f"{n_filtered} {'article' if singular else 'articles'} passed the filter",
        flush=True,
    )

    if n_filtered == 0:
        print(
            "Error: no articles passed the inclusion filter; aborting",
            file=sys.stderr,
            flush=True,
        )
        return 1

    category_lower = category_id.lower()
    output_dir = pathlib.Path("docs") / "arxiv" / category_lower
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "atom.xml"

    # Capture committed bytes before any changes so the commit guard can
    # compare the previously committed version with the generated feed.
    committed_bytes = output_path.read_bytes() if output_path.exists() else None

    archive_prior_week_feed(output_path, today)
    feed_bytes = build_feed(filtered, category_id, strict_mode, github_repository)
    output_path.write_bytes(feed_bytes)

    if feeds_are_identical(committed_bytes, feed_bytes):
        print("no change: feed unchanged", flush=True)
    else:
        print(build_commit_message(feed_bytes), flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
