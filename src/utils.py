"""Shared utilities for the arxiv feed pipeline."""

import datetime
import logging
import os
import pathlib
import re
import xml.etree.ElementTree as ET

# Arxiv categories follow the pattern subject(-subsubject)?(.archive)?
# e.g. cs.AI, cs.cv, astro-ph.HE, gr-qc. Letters only; no path separators,
# whitespace, or directory-traversal sequences are permitted. This guards
# against accidental misconfiguration and path-traversal values such as
# "../etc/passwd" reaching the docs/arxiv/{category}/ filesystem path.
_ARXIV_CATEGORY_PATTERN = re.compile(r"^[a-zA-Z]+(-[a-zA-Z]+)?(\.[a-zA-Z]+)?$")

_ATOM_NS = "http://www.w3.org/2005/Atom"

_logger = logging.getLogger(__name__)


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


def build_commit_message(atom_xml_path: pathlib.Path) -> str:
    """Read the feed at atom_xml_path and return the commit message string."""
    return build_commit_message_from_bytes(atom_xml_path.read_bytes())


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
    entries = root.findall(f"{{{_ATOM_NS}}}entry")
    n = len(entries)
    if n == 0:
        raise ValueError(
            "build_commit_message: feed contains no <entry> elements"
        )
    article_word = "article" if n == 1 else "articles"
    published_dates: list[str] = []
    for entry in entries:
        published_elem = entry.find(f"{{{_ATOM_NS}}}published")
        if published_elem is not None and published_elem.text:
            published_dates.append(published_elem.text)
    # RFC 3339 dates with the same format sort lexicographically by chronology.
    newest_date = max(published_dates)
    # Parse the full RFC 3339 timestamp as a timezone-aware datetime and
    # convert to UTC before extracting the date.  fromisoformat handles the
    # "Z" UTC suffix in Python 3.11+.
    entry_dt = datetime.datetime.fromisoformat(newest_date)
    entry_date = entry_dt.astimezone(datetime.timezone.utc).date()
    iso = entry_date.isocalendar()
    week_str = f"{iso.year}-W{iso.week:02d}"
    return f"Update {week_str} feed ({n} {article_word})"


def include_article(
    primary_category: str,
    comment: str | None,
    abstract_url: str = "",
    published: str = "",
    title: str = "",
) -> bool:
    """
    Return True if the article should be included in the feed.

    Both conditions must hold:
    1. Category condition: when strict mode is enabled, the article's primary
       category must match the configured ARXIV_CATEGORY_ID (case-insensitive);
       when strict mode is disabled, any primary category is accepted.
    2. Comment URL condition: the arxiv:comment field must contain at least one
       https:// URL; absent or empty comment fields are treated as no URL.

    Reads ARXIV_CATEGORY_ID and ARXIV_CATEGORY_STRICT from the environment via
    resolve_category_id and resolve_strict_mode.

    Parameters:
      primary_category: the article's primary arxiv category (e.g. "cs.AI")
      comment:          the arxiv:comment field text, or None when absent
      abstract_url:     arxiv abstract page URL; included in log output for traceability
      published:        RFC 3339 first-publication date; included in log output for traceability
      title:            article title; included in log output for traceability
    """
    category_id = resolve_category_id()
    strict_mode = resolve_strict_mode()

    if strict_mode and primary_category.lower() != category_id.lower():
        _logger.info(
            "rejected (strict category mismatch): primary=%s expected=%s"
            " published=%s title=%s url=%s",
            primary_category, category_id, published, title, abstract_url,
        )
        return False

    if not comment:
        _logger.info(
            "rejected (no comment): primary=%s published=%s title=%s url=%s",
            primary_category, published, title, abstract_url,
        )
        return False

    if "https://" not in comment:
        _logger.info(
            "rejected (no comment URL): primary=%s published=%s title=%s url=%s",
            primary_category, published, title, abstract_url,
        )
        return False

    _logger.info(
        "included: primary=%s published=%s title=%s url=%s",
        primary_category, published, title, abstract_url,
    )
    return True


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


def check_feed_staleness(
    atom_xml_path: pathlib.Path,
    today: datetime.date,
    max_staleness_days: int,
) -> int:
    """
    Return 1 if the newest <entry><published> date in atom_xml_path is more
    than max_staleness_days whole calendar days before today; return 0
    otherwise.

    Pass max_staleness_days=-1 to skip the check unconditionally (returns 0).
    Returns 0 when atom_xml_path does not exist or contains no <entry> elements
    with a <published> date.  Callers must validate max_staleness_days before
    calling: it must be -1 or a positive integer.

    Parameters:
      atom_xml_path:      path to the Atom feed file to check
      today:              reference date (UTC) for the staleness comparison
      max_staleness_days: -1 to skip; positive integer as the maximum age in
                          days before the feed is considered stale
    """
    if max_staleness_days == -1:
        return 0

    if not atom_xml_path.exists():
        return 0

    feed_bytes = atom_xml_path.read_bytes()
    root = ET.fromstring(feed_bytes)
    published_dates: list[str] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        published_elem = entry.find(f"{{{_ATOM_NS}}}published")
        if published_elem is not None and published_elem.text:
            published_dates.append(published_elem.text)

    if not published_dates:
        return 0

    newest_date_str = max(published_dates)
    # fromisoformat handles the "Z" UTC suffix in Python 3.11+.
    entry_dt = datetime.datetime.fromisoformat(newest_date_str)
    entry_date = entry_dt.astimezone(datetime.timezone.utc).date()
    delta_days = (today - entry_date).days

    if delta_days > max_staleness_days:
        _logger.error(
            "feed is stale: newest entry %s is %d days old (threshold: %d days)",
            newest_date_str,
            delta_days,
            max_staleness_days,
        )
        return 1
    return 0
