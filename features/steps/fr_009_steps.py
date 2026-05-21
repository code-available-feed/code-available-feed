"""Step definitions for FR-009: Feed self-URL construction."""

import os
import xml.etree.ElementTree as ET

from behave import given, then, when

import src.pipeline_feed
from atom_ns import ATOM_NS


@when("the feed self-URL is constructed")
def step_construct_feed_self_url(context):
    """Call build_feed_url with the current env-var values and store the result."""
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    category_id = src.pipeline_feed.resolve_category_id()
    context.feed_self_url = src.pipeline_feed.build_feed_url(
        github_repository, category_id
    )


@then('the feed self-URL is "{expected}"')
def step_feed_self_url_is(context, expected):
    assert context.feed_self_url == expected, (
        f"Expected feed self-URL {expected!r}, got {context.feed_self_url!r}"
    )


@given('one input article whose abstract page URL is "{abstract_url}"')
def step_one_article_with_abstract_url(context, abstract_url):
    """Provide a single Article with a specific abstract page URL."""
    context.articles = [
        src.pipeline_feed.Article(
            title="Any Paper Title",
            authors=["Test Author"],
            primary_category="cs.AI",
            abstract_url=abstract_url,
            published="2026-05-12T11:30:00Z",
            updated="2026-05-12T11:30:00Z",
            comment=None,
            comment_urls=["https://example.com/"],
        )
    ]


@then('the feed-level id element value is "{expected}"')
def step_feed_level_id(context, expected):
    id_elem = context.feed_root.find(f"{{{ATOM_NS}}}id")
    assert id_elem is not None, "No id element in feed"
    assert id_elem.text == expected, (
        f"Expected feed id {expected!r}, got {id_elem.text!r}"
    )


@then('the feed-level link element with rel "{rel}" has href "{expected}"')
def step_feed_level_link_href(context, rel, expected):
    for link_elem in context.feed_root.findall(f"{{{ATOM_NS}}}link"):
        if link_elem.get("rel") == rel:
            actual_href = link_elem.get("href")
            assert actual_href == expected, (
                f"Expected href {expected!r}, got {actual_href!r}"
            )
            return
    assert False, f"No link element with rel={rel!r} found in feed"


@then('the entry id element value is "{expected}"')
def step_entry_id_element_value(context, expected):
    entries = context.feed_root.findall(f"{{{ATOM_NS}}}entry")
    assert entries, "No entries found in generated feed"
    id_elem = entries[0].find(f"{{{ATOM_NS}}}id")
    assert id_elem is not None, "No id element in first entry"
    assert id_elem.text == expected, (
        f"Expected entry id {expected!r}, got {id_elem.text!r}"
    )
