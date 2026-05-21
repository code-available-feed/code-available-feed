"""Step definitions for FR-015: Graceful API error continuation and feed staleness alert."""

import pathlib
import tempfile

from behave import given, then, when

import src.pipeline_feed


@given('a minimal feed file "{filepath}" with newest entry published "{published_date}"')
def step_create_minimal_feed(context, filepath, published_date):
    """
    Create a minimal valid Atom feed file containing one entry with the given
    published date, placing it at filepath relative to context.run_dir.

    Delegates serialization to src.pipeline_feed.build_feed so the bytes
    match the production feed format exactly.  Creates context.run_dir if it
    has not already been created by a preceding step.
    """
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    feed_path = context.run_dir / filepath
    feed_path.parent.mkdir(parents=True, exist_ok=True)

    article = {
        "title": "Test Article",
        "authors": ["Test Author"],
        "primary_category": "cs.AI",
        "abstract_url": "https://arxiv.org/abs/0000.00000v1",
        "published": published_date,
        "updated": published_date,
        "comment_urls": ["https://example.com/"],
    }
    feed_bytes = src.pipeline_feed.build_feed(
        [article],
        category_id="cs.AI",
        strict_mode=False,
        github_repository="owner/code-available-feed",
    )
    feed_path.write_bytes(feed_bytes)


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
