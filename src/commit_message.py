"""
FR-006 commit message construction.

The string is used in two places: as a stdout log line emitted by the
pipeline and as the commit message subject of the gh-pages orphan commit
produced by scripts/deploy_orphan.sh. Both call sites reach this module so
the two uses cannot drift.
"""

import argparse
import datetime
import pathlib
import sys
import xml.etree.ElementTree as ET


_ATOM_NS = "http://www.w3.org/2005/Atom"


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
    entry_date = datetime.date.fromisoformat(newest_date[:10])
    iso = entry_date.isocalendar()
    week_str = f"{iso.year}-W{iso.week:02d}"
    return f"Update {week_str} feed ({n} {article_word})"


def build_commit_message(atom_xml_path: pathlib.Path) -> str:
    """Read the feed at atom_xml_path and return the commit message string."""
    return build_commit_message_from_bytes(atom_xml_path.read_bytes())


def main() -> int:
    """CLI: print the commit message for the feed at --filename to stdout."""
    parser = argparse.ArgumentParser(
        description=(
            "Print the FR-006 commit message for a generated atom.xml feed."
        )
    )
    parser.add_argument(
        "--filename",
        required=True,
        type=pathlib.Path,
        help="Path to the generated atom.xml file.",
    )
    args = parser.parse_args()
    print(build_commit_message(args.filename))
    return 0


if __name__ == "__main__":
    sys.exit(main())
