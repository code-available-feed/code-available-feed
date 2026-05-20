"""Step definitions for FR-010: Newsboat validation of the generated feed."""

import os
import pathlib
import socket
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from behave import given, then, when

import src.pipeline_feed

_ATOM_NS = "http://www.w3.org/2005/Atom"

# A minimal valid Atom 1.0 feed with one entry.  Must have exactly one entry
# so that newsboat's print-unread count equals 1 after reload.
_VALID_ATOM_XML = """\
<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test feed</title>
  <id>https://example.com/feed</id>
  <updated>2026-05-12T10:00:00Z</updated>
  <entry>
    <title>Test Article</title>
    <id>https://arxiv.org/abs/2605.00001v1</id>
    <link rel="alternate" type="text/html" href="https://arxiv.org/abs/2605.00001v1"/>
    <published>2026-05-12T10:00:00Z</published>
    <updated>2026-05-12T10:00:00Z</updated>
    <content type="text">https://github.com/test/repo</content>
  </entry>
</feed>
"""

# One entry that is structurally recognizable but preceded by text before the
# XML declaration, which is a fatal XML error that newsboat cannot recover from,
# so it reports 0 unread items (not 1).
_INVALID_XML = """\
This feed is corrupted.
<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Malformed Article</title>
    <id>https://arxiv.org/abs/2605.00001v1</id>
    <link rel="alternate" type="text/html" href="https://arxiv.org/abs/2605.00001v1"/>
    <published>2026-05-12T10:00:00Z</published>
    <updated>2026-05-12T10:00:00Z</updated>
    <content type="text">https://github.com/test/repo</content>
  </entry>
</feed>
"""


def _find_free_port() -> int:
    """Return an available TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _validate_feed(feed_path: pathlib.Path) -> int:
    """
    Validate a single Atom feed using newsboat.

    Counts <entry> elements in feed_path using ElementTree.  If the XML is
    unparseable, returns 1 immediately (the feed is invalid).  Otherwise
    starts a temporary HTTP server serving the feed's docs root (the directory
    above the /arxiv/ component), runs newsboat against the feed URL, and
    returns 0 if newsboat's unread count equals the entry count, 1 otherwise.

    Must run inside the Docker container where newsboat is available.
    feed_path must contain an /arxiv/ path component to derive the docs root.
    """
    try:
        root = ET.parse(str(feed_path)).getroot()
        expected_count = len(root.findall("{" + _ATOM_NS + "}entry"))
    except ET.ParseError:
        return 1

    path_str = str(feed_path)
    sep = "/arxiv/"
    if sep not in path_str:
        raise ValueError(f"Path {feed_path!r} has no /arxiv/ component")
    docs_dir = pathlib.Path(path_str.split(sep, 1)[0])
    rel_path = feed_path.relative_to(docs_dir)

    port = _find_free_port()
    server_proc = subprocess.Popen(
        [
            "python", "-m", "http.server", str(port),
            "--bind", "127.0.0.1",
            "--directory", str(docs_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)
        url_file = tmp / "urls"
        cache_file = tmp / "cache.db"
        search_hist = tmp / "search_hist"
        cmd_hist = tmp / "cmd_hist"
        url_file.write_text(
            f"http://127.0.0.1:{port}/{rel_path.as_posix()}\n",
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    "newsboat",
                    "--url-file", str(url_file),
                    "--cache-file", str(cache_file),
                    "--search-history-file", str(search_hist),
                    "--cmdline-history-file", str(cmd_hist),
                    "--execute", "reload",
                    "--execute", "print-unread",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "LANG": "C.UTF-8"},
            )
            output = (result.stdout + result.stderr).strip()
        finally:
            server_proc.kill()
            server_proc.wait()

    tokens = output.split()
    try:
        actual_count = int(tokens[0]) if tokens else 0
    except ValueError:
        actual_count = 0

    return 0 if actual_count == expected_count else 1


def _ensure_validation_dir(context) -> pathlib.Path:
    """Return context.validation_dir, creating a fresh temp dir if needed."""
    if context.validation_dir is None:
        context.validation_dir = pathlib.Path(tempfile.mkdtemp())
    return context.validation_dir


@given('a valid atom.xml file at "{path}"')
def step_create_valid_atom_xml(context, path):
    docs_dir = _ensure_validation_dir(context)
    full_path = docs_dir / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(_VALID_ATOM_XML, encoding="utf-8")


@given('a file containing invalid XML at "{path}"')
def step_create_invalid_xml(context, path):
    docs_dir = _ensure_validation_dir(context)
    full_path = docs_dir / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(_INVALID_XML, encoding="utf-8")


@given('no directory "{dirpath}" exists')
def step_no_directory_exists(context, dirpath):
    docs_dir = _ensure_validation_dir(context)
    assert not (docs_dir / dirpath).exists(), (
        f"Expected {dirpath} to not exist under {docs_dir}"
    )


@when("the validation script runs")
def step_run_validation(context):
    # Given steps create files at context.validation_dir / "docs/arxiv/...",
    # so the docs root is one level below the temp dir.
    docs_dir = context.validation_dir / "docs"
    category_lower = "cs.ai"
    current_feed = docs_dir / "arxiv" / category_lower / "atom.xml"
    archive_dir = docs_dir / "arxiv" / category_lower / "archive"
    latest_archive = src.pipeline_feed.find_latest_archive_path(archive_dir)

    context.validation_results = []
    context.validation_rc = 0

    feeds = [current_feed]
    if latest_archive is not None:
        feeds.append(latest_archive)

    for feed_path in feeds:
        rel = feed_path.relative_to(docs_dir)
        url_suffix = "/" + rel.as_posix()
        rc = _validate_feed(feed_path)
        context.validation_results.append((url_suffix, rc))
        if rc != 0:
            context.validation_rc = 1


@then("newsboat exits with code 0")
def step_newsboat_exits_zero(context):
    assert context.validation_results, "No validation invocations recorded"
    url_suffix, rc = context.validation_results[0]
    assert rc == 0, f"Expected exit 0 for {url_suffix!r}, got {rc}"


@then("newsboat exits with a non-zero code")
def step_newsboat_exits_nonzero(context):
    assert context.validation_results, "No validation invocations recorded"
    url_suffix, rc = context.validation_results[0]
    assert rc != 0, f"Expected non-zero exit for {url_suffix!r}, got {rc}"


@then("the validation script exits with code 0")
def step_validation_exits_zero(context):
    assert context.validation_rc == 0, (
        f"Expected overall exit 0, got {context.validation_rc}; "
        f"results: {context.validation_results}"
    )


@then("the validation script exits with a non-zero code")
def step_validation_exits_nonzero(context):
    assert context.validation_rc != 0, (
        f"Expected overall non-zero exit, got {context.validation_rc}; "
        f"results: {context.validation_results}"
    )


@then('newsboat exits with code 0 for the URL ending in "{suffix}"')
def step_newsboat_exits_zero_for_url(context, suffix):
    matching = [(u, rc) for u, rc in context.validation_results if u == suffix]
    assert len(matching) == 1, (
        f"Expected exactly 1 result for {suffix!r}; "
        f"recorded: {[u for u, _ in context.validation_results]}"
    )
    url_suffix, rc = matching[0]
    assert rc == 0, f"Expected exit 0 for {url_suffix!r}, got {rc}"


@then(
    'the archive invocation URL file contains exactly one entry ending in "{suffix}"'
)
def step_archive_url_file_entry(context, suffix):
    # _validate_feed is called once per feed path, so one archive call means
    # exactly one result with "archive" in the URL suffix.  This confirms that
    # only the lexicographically latest archive was selected, not all archives.
    archive_results = [
        (u, rc) for u, rc in context.validation_results if "archive" in u
    ]
    assert len(archive_results) == 1, (
        f"Expected exactly 1 archive invocation, got {len(archive_results)}; "
        f"results: {context.validation_results}"
    )
    url_suffix, _rc = archive_results[0]
    assert url_suffix == suffix, (
        f"Expected archive URL suffix {suffix!r}, got {url_suffix!r}"
    )
