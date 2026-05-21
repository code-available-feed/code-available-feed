"""Step definitions for FR-013: Diagnostic logging to stdout."""

import pathlib
import tempfile

from behave import given, then

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
