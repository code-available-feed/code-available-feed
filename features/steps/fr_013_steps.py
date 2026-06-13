"""Step definitions for FR-013: Diagnostic logging to stdout."""

import json
import pathlib
import tempfile
from typing import Any

from behave import given, then

import src.pipeline_feed

# A minimal valid Atom feed used as "known previous content" in diff scenarios.
# It contains no entries so it differs from any pipeline output that includes
# at least one article, guaranteeing the unified diff produces --- and +++ lines.
_KNOWN_PREVIOUS_ATOM_XML = b"""\
<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>previous week feed</title>
  <id>https://example.com/previous</id>
</feed>
"""


@given(
    "the fixture server returns {n_entries:d} entries where"
    " {n_satisfy:d} satisfy the inclusion filter"
)
def step_fixture_partial_comment_urls(context, n_entries, n_satisfy):
    """
    Configure the fixture server to return n_entries entries for start=0,
    where only the first n_satisfy entries carry a comment https:// URL.

    Entries without a comment URL fail the inclusion filter (FR-002 condition 2).
    """
    context.fixture_server.set_response(
        start=0,
        status=200,
        n_entries=n_entries,
        n_have_comment_url=n_satisfy,
    )


@given(
    "the fixture server returns {n_entries:d} entries where"
    " all {n_all:d} satisfy the inclusion filter"
)
def step_fixture_all_satisfy(context, n_entries, n_all):
    """
    Configure the fixture server to return n_entries entries for start=0,
    all with a comment https:// URL so all pass the inclusion filter.

    n_all must equal n_entries; the parameter exists for readability in the
    feature file.
    """
    assert n_entries == n_all, (
        f"Step mismatch: n_entries={n_entries} but n_all={n_all}; "
        "these must be equal"
    )
    context.fixture_server.set_response(
        start=0, status=200, n_entries=n_entries
    )


@given('no file "{filepath}" exists in a fresh temporary directory')
def step_no_file_in_fresh_dir(context, filepath):
    """
    Create a fresh temporary directory with no pre-existing file at filepath.

    This step uses different wording from the identical fr_001_steps step
    ('no "{filepath}" file exists...') to allow the feature file phrasing
    'no file "..." exists...' to read naturally in the context of diff tests.
    """
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    assert not (context.run_dir / filepath).exists(), (
        f"Unexpected file {filepath} in fresh temp dir {context.run_dir}"
    )


@given('an existing file "{filepath}" with known previous content')
def step_existing_file_known_content(context, filepath):
    """
    Create a minimal valid atom.xml at filepath inside a fresh temp directory.

    The "known previous content" is a feed with no entries so it differs from
    any generated feed that includes articles, ensuring the unified diff
    produces --- and +++ header lines.
    """
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    full_path = context.run_dir / filepath
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(_KNOWN_PREVIOUS_ATOM_XML)


@then('stdout contains a line containing "{text}"')
def step_stdout_contains_line_with(context, text):
    """Assert that at least one line of pipeline stdout contains text."""
    lines = context.pipeline_result.stdout.splitlines()
    assert any(text in line for line in lines), (
        f"No stdout line contains {text!r}\n"
        f"stdout:\n{context.pipeline_result.stdout}\n"
        f"stderr:\n{context.pipeline_result.stderr}"
    )


@then('stdout contains a line starting with "{text}"')
def step_stdout_line_starts_with(context, text):
    """Assert that at least one line of pipeline stdout starts with text."""
    lines = context.pipeline_result.stdout.splitlines()
    assert any(line.startswith(text) for line in lines), (
        f"No stdout line starts with {text!r}\n"
        f"stdout:\n{context.pipeline_result.stdout}\n"
        f"stderr:\n{context.pipeline_result.stderr}"
    )


@then('stdout does not contain any line starting with "{text}"')
def step_stdout_no_line_starts_with(context, text):
    """Assert that no line of pipeline stdout starts with text."""
    lines = context.pipeline_result.stdout.splitlines()
    matching = [line for line in lines if line.startswith(text)]
    assert not matching, (
        f"Expected no stdout line starting with {text!r},"
        f" but found: {matching}\n"
        f"stdout:\n{context.pipeline_result.stdout}"
    )


@then(
    'at least one stdout line parses as JSON with keys'
    ' "{k1}", "{k2}", "{k3}", "{k4}", "{k5}"'
)
def step_stdout_json_with_keys(context, k1, k2, k3, k4, k5):
    """Assert that at least one stdout line is valid JSON containing all five keys."""
    required_keys = {k1, k2, k3, k4, k5}
    lines = context.pipeline_result.stdout.splitlines()
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if required_keys.issubset(obj.keys()):
            return
    assert False, (
        f"No stdout line parses as JSON with all keys {sorted(required_keys)}\n"
        f"stdout:\n{context.pipeline_result.stdout}"
    )


# ---------------------------------------------------------------------------
# Steps for cache/enrichment logging scenarios (FR-013 gaps identified in
# debug-log-problem.md).
# ---------------------------------------------------------------------------


def _make_dummy_article(abstract_url: str) -> src.pipeline_feed.Article:
    """Return a minimal Article for use as a placeholder in build_feed calls.

    build_feed requires at least one article.  This dummy article is never
    processed by the pipeline; it only satisfies that constraint when
    pre-loading a prior atom.xml.
    """
    return src.pipeline_feed.Article(
        title="Dummy Article",
        authors=["Dummy Author"],
        primary_category="cs.AI",
        abstract_url=abstract_url,
        published="2026-05-12T10:00:00Z",
        updated="2026-05-12T10:00:00Z",
        abstract="Dummy abstract.",
        comment=None,
        comment_urls=[],
    )


def _write_prior_atom_xml(
    context: Any,
    processed_rows: list[dict[str, str]],
) -> None:
    """Write docs/arxiv/cs.ai/atom.xml inside context.run_dir with the given processed entries.

    Called before the pipeline runs so that load_processed finds these entries
    as prior_processed_full.  One dummy article is included to satisfy
    build_feed's requirement; only the processed element is read by the pipeline.
    """
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    output_dir = context.run_dir / "docs" / "arxiv" / "cs.ai"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "atom.xml"

    processed: dict[str, src.pipeline_feed.ProcessedEntry] = {}
    for row in processed_rows:
        repo_urls_str = row.get("repo_urls", "")
        repo_urls = tuple(u for u in repo_urls_str.split(";") if u) if repo_urls_str else ()
        updated = row["updated"]
        processed[row["url"]] = src.pipeline_feed.ProcessedEntry(
            published=row.get("published", updated),
            updated=updated,
            repo_found_in=row.get("repo_found_in", ""),
            repo_urls=repo_urls,
        )

    dummy = _make_dummy_article("https://arxiv.org/abs/dummy.000000v1")
    feed_bytes = src.pipeline_feed.build_feed(
        articles=[dummy._replace(repo_found_in="comment", repo_urls=("https://example.com/",))],
        processed=processed,
        category_id="cs.AI",
        strict_mode=False,
        github_repository="owner/code-available-feed",
    )
    output_path.write_bytes(feed_bytes)


@given("the prior atom.xml contains processed entries")
def step_prior_atom_xml_with_processed_table(context):
    """Create docs/arxiv/cs.ai/atom.xml with processed entries from a Gherkin table.

    Table columns: url, repo_found_in, updated (repo_urls is optional).
    The updated date must be within the Background's PIPELINE_TODAY window
    [2026-05-06, 2026-05-14].
    """
    rows = [
        {heading: row[heading] for heading in row.headings}
        for row in context.table
    ]
    _write_prior_atom_xml(context, rows)


@given(
    "the fixture server returns {n_entries:d} entries without any URLs"
    " for query parameter \"start={start_value:d}\""
)
def step_fixture_entries_without_urls(context, n_entries, start_value):
    """Configure the fixture server to return n_entries with no comment and no abstract URL."""
    context.fixture_server.set_response(
        start=start_value,
        status=200,
        n_entries=n_entries,
        n_have_comment_url=0,
        n_have_abstract_url=0,
    )


@given(
    "the fixture server returns {n_entries:d} entries with abstract URLs"
    " for query parameter \"start={start_value:d}\""
)
def step_fixture_entries_with_abstract_urls(context, n_entries, start_value):
    """Configure the fixture server to return n_entries all with github.com abstract URLs."""
    context.fixture_server.set_response(
        start=start_value,
        status=200,
        n_entries=n_entries,
        n_have_comment_url=0,
        n_have_abstract_url=n_entries,
    )


@then('stdout contains a log message containing "{text}"')
def step_stdout_log_message_containing(context, text):
    """Assert that at least one JSON log line has a message field containing text."""
    lines = context.pipeline_result.stdout.splitlines()
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if text in obj.get("message", ""):
            return
    assert False, (
        f"No JSON log line has message containing {text!r}\n"
        f"stdout:\n{context.pipeline_result.stdout}\n"
        f"stderr:\n{context.pipeline_result.stderr}"
    )


@then('stdout contains a log message containing all of "{text1}" and "{text2}"')
def step_stdout_log_message_containing_all(context, text1, text2):
    """Assert that at least one JSON log line has a message field containing both text1 and text2."""
    lines = context.pipeline_result.stdout.splitlines()
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", "")
        if text1 in msg and text2 in msg:
            return
    assert False, (
        f"No JSON log line has message containing both {text1!r} and {text2!r}\n"
        f"stdout:\n{context.pipeline_result.stdout}\n"
        f"stderr:\n{context.pipeline_result.stderr}"
    )


@then('stdout contains {n:d} log messages containing "{text}"')
def step_stdout_n_log_messages_containing(context, n, text):
    """Assert that exactly n JSON log lines have a message field containing text."""
    lines = context.pipeline_result.stdout.splitlines()
    matches = []
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if text in obj.get("message", ""):
            matches.append(obj["message"])
    assert len(matches) == n, (
        f"Expected {n} log message(s) containing {text!r},"
        f" found {len(matches)}: {matches}\n"
        f"stdout:\n{context.pipeline_result.stdout}\n"
        f"stderr:\n{context.pipeline_result.stderr}"
    )
