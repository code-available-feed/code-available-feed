"""Step definitions for FR-015: Graceful API error continuation and feed staleness alert."""

import pathlib
import tempfile
import xml.etree.ElementTree as ET

from behave import given, then, when

import src.pipeline_feed

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
    Call src.pipeline_feed.run_staleness_check directly with context.run_dir as base_dir.
    Stores the integer return code in context.staleness_returncode.
    """
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    context.staleness_returncode = src.pipeline_feed.run_staleness_check(context.run_dir)


@then("the staleness check exits with code 0")
def step_staleness_exits_zero(context):
    """Assert that run_staleness_check returned 0."""
    assert context.staleness_returncode == 0, (
        f"Expected staleness check return code 0, got {context.staleness_returncode}"
    )


@then("the staleness check exits with non-zero code")
def step_staleness_exits_nonzero(context):
    """Assert that run_staleness_check returned a non-zero code."""
    assert context.staleness_returncode != 0, (
        f"Expected staleness check non-zero return code, got {context.staleness_returncode}"
    )
