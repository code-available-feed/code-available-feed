"""Step definitions for FR-005: Weekly storage path and week-rollover archive."""

import io
import pathlib
import tempfile
import xml.etree.ElementTree as ET

from behave import given, then

_ATOM_NS = "http://www.w3.org/2005/Atom"

# Register the default namespace so the serialiser writes <feed xmlns="...">
# rather than <ns0:feed xmlns:ns0="...">.
ET.register_namespace("", _ATOM_NS)


def _build_minimal_feed(published: str) -> bytes:
    """
    Return minimal Atom XML bytes with one <entry> at the given published date.

    Parameters:
      published: RFC 3339 date string, e.g. "2026-05-08T12:00:00Z"
    """
    root = ET.Element(f"{{{_ATOM_NS}}}feed")
    entry = ET.SubElement(root, f"{{{_ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{_ATOM_NS}}}published").text = published
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


@given('an existing "{filepath}" whose newest entry published date is "{published}"')
def step_create_existing_feed(context, filepath, published):
    """
    Create a fresh temporary run directory, write a minimal Atom feed at
    filepath, and save the feed bytes in context.prior_atom_xml_bytes for
    later byte-equality assertions.
    """
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    full_path = context.run_dir / filepath
    full_path.parent.mkdir(parents=True, exist_ok=True)
    feed_bytes = _build_minimal_feed(published)
    full_path.write_bytes(feed_bytes)
    context.prior_atom_xml_bytes = feed_bytes


@then('the output file path is "{expected_path}"')
def step_output_file_path_exists(context, expected_path):
    """Assert that the pipeline wrote a file at expected_path inside run_dir."""
    full_path = context.run_dir / expected_path
    assert full_path.exists(), (
        f"Expected output at {full_path}, but it does not exist\n"
        f"stdout: {context.pipeline_result.stdout}\n"
        f"stderr: {context.pipeline_result.stderr}"
    )


@then('no file exists under "{dirpath}"')
def step_no_file_under(context, dirpath):
    """Assert that no files were created recursively under dirpath in run_dir."""
    full_dir = context.run_dir / dirpath
    if not full_dir.exists():
        return
    files = list(full_dir.rglob("*"))
    assert not files, (
        f"Expected no files under {full_dir}, but found: {files}"
    )


@then('the file "{filepath}" exists')
def step_file_exists(context, filepath):
    """Assert that filepath exists inside run_dir."""
    full_path = context.run_dir / filepath
    assert full_path.exists(), (
        f"Expected file {full_path} to exist, but it does not\n"
        f"stdout: {context.pipeline_result.stdout}\n"
        f"stderr: {context.pipeline_result.stderr}"
    )


@then(
    'the contents of "{filepath}" match the prior contents of "{prior_filepath}"'
)
def step_contents_match_prior(context, filepath, prior_filepath):
    """
    Assert that the archive file bytes equal context.prior_atom_xml_bytes.

    prior_filepath is the path of the original file before the pipeline run;
    the parameter name is used only for the error message.
    """
    actual_path = context.run_dir / filepath
    actual_bytes = actual_path.read_bytes()
    assert actual_bytes == context.prior_atom_xml_bytes, (
        f"Contents of {filepath} do not match prior contents of {prior_filepath}\n"
        f"expected length: {len(context.prior_atom_xml_bytes)}, "
        f"actual length: {len(actual_bytes)}"
    )
