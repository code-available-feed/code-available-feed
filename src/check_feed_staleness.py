"""
Staleness check entry point: verify the newest feed entry is within
ARXIV_MAX_STALENESS_DAYS of today UTC.

Environment variables read by this module:
  ARXIV_CATEGORY_ID        optional; default "cs.AI"
  ARXIV_MAX_STALENESS_DAYS optional; -1 (default, check disabled) or a positive
                           integer (maximum age in days before the feed is stale)
  PIPELINE_TODAY           optional; ISO date (YYYY-MM-DD) overrides the current UTC date
"""

import datetime
import logging
import os
import pathlib
import sys

import src.utils

_logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure root logger: ERROR and above to stderr as plain text."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.ERROR)


def main() -> int:
    """Run the staleness check and return the process exit code."""
    _setup_logging()

    try:
        category_id = src.utils.resolve_category_id()
    except ValueError as exc:
        _logger.error("%s", exc)
        return 1

    category_lower = category_id.lower()

    max_staleness_days_str = os.environ.get("ARXIV_MAX_STALENESS_DAYS", "-1")
    try:
        max_staleness_days = int(max_staleness_days_str)
    except ValueError:
        _logger.error(
            "ARXIV_MAX_STALENESS_DAYS must be -1 or a positive integer, got: %r",
            max_staleness_days_str,
        )
        return 1

    if max_staleness_days != -1 and max_staleness_days < 1:
        _logger.error(
            "ARXIV_MAX_STALENESS_DAYS must be -1 or a positive integer, got: %d",
            max_staleness_days,
        )
        return 1

    today_override = os.environ.get("PIPELINE_TODAY")
    if today_override:
        today = datetime.date.fromisoformat(today_override)
    else:
        today = datetime.datetime.now(datetime.timezone.utc).date()

    feed_path = pathlib.Path("docs") / "arxiv" / category_lower / "atom.xml"

    return src.utils.check_feed_staleness(feed_path, today, max_staleness_days)


if __name__ == "__main__":
    sys.exit(main())
