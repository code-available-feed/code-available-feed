"""Step definitions for FR-004: Atom 1.0 feed generation."""

import os
import xml.etree.ElementTree as ET

from behave import given, then, when

import src.pipeline_feed
from atom_ns import ATOM_NS


def _parse_authors(value: str) -> list[str]:
    """Split a comma-separated author list into individual names."""
    return [name.strip() for name in value.split(",")]


def _parse_urls(value: str) -> list[str]:
    """Split a comma-separated URL list into individual URLs."""
    return [url.strip() for url in value.split(",")]


def _get_entry(context) -> ET.Element:
    """Return the first entry element from the generated feed."""
    entries = context.feed_root.findall(f"{{{ATOM_NS}}}entry")
    assert entries, "No entries found in generated feed"
    return entries[0]


@given("one input article with")
def step_one_article_with_table(context):
    """
    Build one article dict from a two-column table with headers 'field' and
    'value'.

    Supported fields: title, authors (comma-separated), primary_category,
    abstract_url, published, updated, comment_urls (comma-separated).
    """
    article: dict = {}
    for row in context.table:
        field = row["field"]
        value = row["value"]
        if field == "authors":
            article["authors"] = _parse_authors(value)
        elif field == "comment_urls":
            article["comment_urls"] = _parse_urls(value)
        else:
            article[field] = value
    context.articles = [article]


@given("three input articles")
def step_three_articles_with_table(context):
    """
    Build three article dicts from a table whose columns are the article fields.

    Column names: title, authors (comma-separated), primary_category,
    abstract_url, published, updated, comment_urls (comma-separated).
    """
    articles = []
    for row in context.table:
        articles.append(
            {
                "title": row["title"],
                "authors": _parse_authors(row["authors"]),
                "primary_category": row["primary_category"],
                "abstract_url": row["abstract_url"],
                "published": row["published"],
                "updated": row["updated"],
                "comment_urls": _parse_urls(row["comment_urls"]),
            }
        )
    context.articles = articles


@given("one input article with any valid fields")
def step_one_article_any_fields(context):
    """Provide a single article with minimal valid field values."""
    context.articles = [
        {
            "title": "Any Paper Title",
            "authors": ["Test Author"],
            "primary_category": "cs.AI",
            "abstract_url": "https://arxiv.org/abs/0000.00000v1",
            "published": "2026-05-12T11:30:00Z",
            "updated": "2026-05-12T11:30:00Z",
            "comment_urls": ["https://example.com/"],
        }
    ]


@when("the feed is generated")
def step_generate_feed(context):
    """Call build_feed and store the result in context for Then steps."""
    category_id = src.pipeline_feed.resolve_category_id()
    strict_mode = src.pipeline_feed.resolve_strict_mode()
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    feed_bytes = src.pipeline_feed.build_feed(
        context.articles, category_id, strict_mode, github_repository
    )
    context.feed_bytes = feed_bytes
    try:
        context.feed_root = ET.fromstring(feed_bytes)
    except ET.ParseError:
        # feed_bytes may be intentionally malformed during NFR-004 mutation
        # testing; Then steps that need feed_root will fail naturally via
        # AttributeError on context.feed_root (None).
        context.feed_root = None


@then('the entry has title "{expected}"')
def step_entry_has_title(context, expected):
    entry = _get_entry(context)
    title_elem = entry.find(f"{{{ATOM_NS}}}title")
    assert title_elem is not None, "No title element in entry"
    assert title_elem.text == expected, (
        f"Expected title {expected!r}, got {title_elem.text!r}"
    )


@then(
    'the entry has author names "{first}" then "{second}" in document order'
)
def step_entry_has_authors_two(context, first, second):
    entry = _get_entry(context)
    names = [
        name_elem.text
        for author_elem in entry.findall(f"{{{ATOM_NS}}}author")
        for name_elem in [author_elem.find(f"{{{ATOM_NS}}}name")]
        if name_elem is not None
    ]
    expected = [first, second]
    assert names == expected, (
        f"Expected authors {expected!r}, got {names!r}"
    )


@then(
    'the entry has category element with term "{term}" and scheme "{scheme}"'
)
def step_entry_has_category(context, term, scheme):
    entry = _get_entry(context)
    cat_elem = entry.find(f"{{{ATOM_NS}}}category")
    assert cat_elem is not None, "No category element in entry"
    actual_term = cat_elem.get("term")
    actual_scheme = cat_elem.get("scheme")
    assert actual_term == term, (
        f"Expected term {term!r}, got {actual_term!r}"
    )
    assert actual_scheme == scheme, (
        f"Expected scheme {scheme!r}, got {actual_scheme!r}"
    )


@then('the entry has id "{expected}"')
def step_entry_has_id(context, expected):
    entry = _get_entry(context)
    id_elem = entry.find(f"{{{ATOM_NS}}}id")
    assert id_elem is not None, "No id element in entry"
    assert id_elem.text == expected, (
        f"Expected id {expected!r}, got {id_elem.text!r}"
    )


@then('the entry has link rel "{rel}" type "{media_type}" with href "{href}"')
def step_entry_has_link(context, rel, media_type, href):
    entry = _get_entry(context)
    for link_elem in entry.findall(f"{{{ATOM_NS}}}link"):
        if (
            link_elem.get("rel") == rel
            and link_elem.get("type") == media_type
        ):
            actual_href = link_elem.get("href")
            assert actual_href == href, (
                f"Expected href {href!r}, got {actual_href!r}"
            )
            return
    assert False, (
        f"No link with rel={rel!r} type={media_type!r} found in entry"
    )


@then('the entry has published "{expected}"')
def step_entry_has_published(context, expected):
    entry = _get_entry(context)
    pub_elem = entry.find(f"{{{ATOM_NS}}}published")
    assert pub_elem is not None, "No published element in entry"
    assert pub_elem.text == expected, (
        f"Expected published {expected!r}, got {pub_elem.text!r}"
    )


@then('the entry has updated "{expected}"')
def step_entry_has_updated(context, expected):
    entry = _get_entry(context)
    upd_elem = entry.find(f"{{{ATOM_NS}}}updated")
    assert upd_elem is not None, "No updated element in entry"
    assert upd_elem.text == expected, (
        f"Expected updated {expected!r}, got {upd_elem.text!r}"
    )


@then('the entry has content type "text" with value "{expected}"')
def step_entry_has_content_text(context, expected):
    entry = _get_entry(context)
    content_elem = entry.find(f"{{{ATOM_NS}}}content")
    assert content_elem is not None, "No content element in entry"
    actual_type = content_elem.get("type")
    assert actual_type == "text", (
        f"Expected content type 'text', got {actual_type!r}"
    )
    # Gherkin does not interpret \n as a newline; convert explicitly.
    expected_text = expected.replace("\\n", "\n")
    assert content_elem.text == expected_text, (
        f"Expected content {expected_text!r}, got {content_elem.text!r}"
    )


@then(
    'the entry published dates in document order are'
    ' "{first}" then "{second}" then "{third}"'
)
def step_entry_published_dates_three(context, first, second, third):
    entries = context.feed_root.findall(f"{{{ATOM_NS}}}entry")
    assert len(entries) == 3, f"Expected 3 entries, got {len(entries)}"
    dates = [
        entry.find(f"{{{ATOM_NS}}}published").text for entry in entries
    ]
    expected = [first, second, third]
    assert dates == expected, (
        f"Expected published dates {expected!r}, got {dates!r}"
    )


@then('the feed-level title element value is "{expected}"')
def step_feed_level_title(context, expected):
    title_elem = context.feed_root.find(f"{{{ATOM_NS}}}title")
    assert title_elem is not None, "No title element in feed"
    assert title_elem.text == expected, (
        f"Expected feed title {expected!r}, got {title_elem.text!r}"
    )


@then('the feed-level updated element value is "{expected}"')
def step_feed_level_updated(context, expected):
    updated_elem = context.feed_root.find(f"{{{ATOM_NS}}}updated")
    assert updated_elem is not None, "No updated element in feed"
    assert updated_elem.text == expected, (
        f"Expected feed updated {expected!r}, got {updated_elem.text!r}"
    )
