"""Step definitions for FR-011: Retry on API failure."""

import os
import pathlib
import xml.etree.ElementTree as ET

from behave import given, then

from atom_ns import ATOM_NS


@given("the fixture server responds with HTTP 503 to the first request")
def step_fixture_503_first_request(context):
    """Configure the fixture server to return 503 for the first request."""
    context.fixture_server.set_initial_response_sequence([(503, 0, 0)])


@given(
    "the fixture server responds with HTTP {status:d} and {n_entries:d} entries"
    " to subsequent requests"
)
def step_fixture_respond_to_subsequent_requests(context, status, n_entries):
    """
    Override the server defaults for all requests not covered by the initial
    sequence or the per-start response table.
    """
    context.fixture_server.set_default(status, n_entries)


@given("the fixture server responds with HTTP 503 to the first 2 requests")
def step_fixture_503_first_two_requests(context):
    """Configure the fixture server to return 503 for the first two requests."""
    context.fixture_server.set_initial_response_sequence(
        [(503, 0, 0), (503, 0, 0)]
    )


@given("the fixture server responds with HTTP 503 to the second request")
def step_fixture_503_second_request(context):
    """
    Configure the fixture server to return 503 for the pagination request.

    The second request uses start=ARXIV_MAX_RESULTS (default 50), which is
    the pagination offset after a first page that returns exactly max_results
    entries (so the pipeline expects more pages to follow).
    """
    max_results = int(os.environ.get("ARXIV_MAX_RESULTS", "50"))
    context.fixture_server.set_response(
        start=max_results, status=503, n_entries=0
    )


@given("the fixture server responds with HTTP 503 to every request")
def step_fixture_503_every_request(context):
    """Override the server default so that every request returns HTTP 503."""
    context.fixture_server.set_default(503, 0)


@given(
    'all {n_entries:d} entries have primary category "{primary_category}"'
    " and a comment URL"
)
def step_all_entries_primary_category(context, n_entries, primary_category):
    """
    Set the primary category for all fixture entries returned by the server.

    The n_entries parameter is present for readability but is not used here
    because the entry count is already configured by the preceding step.
    """
    context.fixture_server.set_default_primary_category(primary_category)


@then("the generated atom.xml contains {n:d} entries")
def step_generated_atom_xml_has_n_entries(context, n):
    """Assert the generated atom.xml contains exactly n <entry> elements."""
    category_lower = os.environ.get("ARXIV_CATEGORY_ID", "cs.AI").lower()
    feed_path = (
        context.run_dir / "docs" / "arxiv" / category_lower / "atom.xml"
    )
    assert feed_path.exists(), (
        f"atom.xml not found at {feed_path}\n"
        f"pipeline stdout: {context.pipeline_result.stdout}\n"
        f"pipeline stderr: {context.pipeline_result.stderr}"
    )
    root = ET.fromstring(feed_path.read_bytes())
    entries = root.findall(f"{{{ATOM_NS}}}entry")
    assert len(entries) == n, (
        f"Expected {n} entries in atom.xml, got {len(entries)}"
    )
