"""Step definitions for FR-015: Graceful API error continuation and feed staleness alert."""

import os
import pathlib
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from behave import given, then, when

_ATOM_NS = "http://www.w3.org/2005/Atom"


@given('a minimal feed file "{filepath}" with newest entry published "{published_date}"')
def step_create_minimal_feed(context, filepath, published_date):
    """
    Create a minimal valid Atom feed file containing one entry with the given
    published date, placing it at filepath relative to context.run_dir.

    Creates context.run_dir if it has not already been created by a preceding step.
    """
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    feed_path = context.run_dir / filepath
    feed_path.parent.mkdir(parents=True, exist_ok=True)

    ET.register_namespace("", _ATOM_NS)
    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    title_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}title")
    title_elem.text = "test"
    id_elem = ET.SubElement(feed, f"{{{_ATOM_NS}}}id")
    id_elem.text = "https://example.com/feed"
    entry = ET.SubElement(feed, f"{{{_ATOM_NS}}}entry")
    pub_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}published")
    pub_elem.text = published_date
    upd_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}updated")
    upd_elem.text = published_date

    feed_path.write_bytes(ET.tostring(feed, encoding="UTF-8", xml_declaration=True))


@when("the staleness check runs")
def step_run_staleness_check(context):
    """
    Run src.check_feed_staleness as a subprocess in context.run_dir, capturing
    stdout and stderr.  Stores the CompletedProcess in context.staleness_result.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = "/app"
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    context.staleness_result = subprocess.run(
        ["python", "-m", "src.check_feed_staleness"],
        cwd=str(context.run_dir),
        env=env,
        capture_output=True,
        text=True,
    )


@then("the staleness check exits with code 0")
def step_staleness_exits_zero(context):
    """Assert that the staleness check subprocess exited with code 0."""
    assert context.staleness_result.returncode == 0, (
        f"Expected staleness check exit code 0, "
        f"got {context.staleness_result.returncode}\n"
        f"stdout: {context.staleness_result.stdout}\n"
        f"stderr: {context.staleness_result.stderr}"
    )


@then("the staleness check exits with non-zero code")
def step_staleness_exits_nonzero(context):
    """Assert that the staleness check subprocess exited with a non-zero code."""
    assert context.staleness_result.returncode != 0, (
        f"Expected staleness check non-zero exit code, "
        f"got {context.staleness_result.returncode}\n"
        f"stdout: {context.staleness_result.stdout}\n"
        f"stderr: {context.staleness_result.stderr}"
    )
