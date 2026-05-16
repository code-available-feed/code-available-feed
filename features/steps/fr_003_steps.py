"""Step definitions for FR-003: Per-article field extraction from the arxiv API response."""

import io
import xml.etree.ElementTree as ET

from behave import given, then, when

import src.pipeline_feed

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"


def _make_entry() -> ET.Element:
    """Return an empty <entry> element in the Atom namespace."""
    return ET.Element(f"{{{_ATOM_NS}}}entry")


def _serialise_entry(entry: ET.Element) -> bytes:
    """Wrap entry in a <feed> root and return UTF-8 Atom XML bytes."""
    root = ET.Element(f"{{{_ATOM_NS}}}feed")
    root.append(entry)
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


@given("an arxiv API entry with")
def step_entry_with_table(context):
    """
    Build an entry element from a two-column table with headers 'element' and 'value'.

    Supported element paths:
      atom:title, atom:author[N]/atom:name, arxiv:primary_category/@term,
      atom:link[@rel='alternate'][@type='text/html']/@href,
      atom:id, atom:published, atom:updated, arxiv:comment.
    """
    entry = _make_entry()
    # Collect indexed author names so they can be inserted in document order
    # after all other elements.
    author_names: dict[int, str] = {}

    for row in context.table:
        element_path = row["element"]
        value = row["value"]

        if element_path == "atom:title":
            ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = value
        elif (
            element_path.startswith("atom:author[")
            and "/atom:name" in element_path
        ):
            bracket_end = element_path.index("]")
            idx = int(element_path[len("atom:author["):bracket_end])
            author_names[idx] = value
        elif element_path == "arxiv:primary_category/@term":
            elem = ET.SubElement(entry, f"{{{_ARXIV_NS}}}primary_category")
            elem.set("term", value)
        elif (
            element_path
            == "atom:link[@rel='alternate'][@type='text/html']/@href"
        ):
            link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
            link.set("rel", "alternate")
            link.set("type", "text/html")
            link.set("href", value)
        elif element_path == "atom:id":
            ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = value
        elif element_path == "atom:published":
            ET.SubElement(entry, f"{{{_ATOM_NS}}}published").text = value
        elif element_path == "atom:updated":
            ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = value
        elif element_path == "arxiv:comment":
            ET.SubElement(entry, f"{{{_ARXIV_NS}}}comment").text = value
        else:
            raise ValueError(
                f"Unsupported element path in step table: {element_path!r}"
            )

    for idx in sorted(author_names):
        author_elem = ET.SubElement(entry, f"{{{_ATOM_NS}}}author")
        ET.SubElement(author_elem, f"{{{_ATOM_NS}}}name").text = (
            author_names[idx]
        )

    context.api_entry = entry


@given('an arxiv API entry whose atom:id is "{id_text}"')
def step_entry_with_id(context, id_text):
    """Create a minimal entry with only an id element."""
    entry = _make_entry()
    ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = id_text
    context.api_entry = entry


@given(
    'the same entry has atom:link rel "{rel}"'
    ' type "{media_type}" with href "{href}"'
)
def step_entry_add_link(context, rel, media_type, href):
    """Append a link element to the entry already in context.api_entry."""
    link = ET.SubElement(context.api_entry, f"{{{_ATOM_NS}}}link")
    link.set("rel", rel)
    link.set("type", media_type)
    link.set("href", href)


@given('an article whose comment is "{comment}"')
def step_article_comment_for_url_extraction(context, comment):
    """Set the comment string for comment URL extraction scenarios."""
    context.article_comment = comment


@given(
    'an arxiv API entry whose atom:published is "{published}"'
    ' and atom:updated is "{updated}"'
)
def step_entry_published_updated(context, published, updated):
    """Create a minimal entry with only published and updated elements."""
    entry = _make_entry()
    ET.SubElement(entry, f"{{{_ATOM_NS}}}published").text = published
    ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = updated
    context.api_entry = entry


@when("the pipeline extracts article fields")
def step_extract_article_fields(context):
    """
    Serialise context.api_entry into a feed document and call parse_entries.

    Stores the first extracted article in context.extracted_article and its
    comment_urls in context.extracted_urls so that shared Then steps can
    access either form.
    """
    body = _serialise_entry(context.api_entry)
    entries = src.pipeline_feed.parse_entries(body)
    assert entries, "parse_entries returned no entries for the constructed feed"
    context.extracted_article = entries[0]
    context.extracted_urls = entries[0]["comment_urls"]


@when("the pipeline extracts the comment URLs")
def step_extract_comment_urls(context):
    """Call extract_comment_urls with context.article_comment."""
    context.extracted_urls = src.pipeline_feed.extract_comment_urls(
        context.article_comment
    )


@then('the recorded title is "{expected}"')
def step_recorded_title(context, expected):
    actual = context.extracted_article["title"]
    assert actual == expected, (
        f"Expected title {expected!r}, got {actual!r}"
    )


@then('the recorded authors in order are "{first}" then "{second}"')
def step_recorded_authors_two(context, first, second):
    actual = context.extracted_article["authors"]
    expected = [first, second]
    assert actual == expected, (
        f"Expected authors {expected!r}, got {actual!r}"
    )


@then('the recorded primary category is "{expected}"')
def step_recorded_primary_category(context, expected):
    actual = context.extracted_article["primary_category"]
    assert actual == expected, (
        f"Expected primary category {expected!r}, got {actual!r}"
    )


@then('the recorded abstract page URL is "{expected}"')
def step_recorded_abstract_url(context, expected):
    actual = context.extracted_article["abstract_url"]
    assert actual == expected, (
        f"Expected abstract URL {expected!r}, got {actual!r}"
    )


@then('the recorded abstract page URL does not start with "{prefix}"')
def step_recorded_abstract_url_no_prefix(context, prefix):
    actual = context.extracted_article["abstract_url"]
    assert not actual.startswith(prefix), (
        f"Expected abstract URL not to start with {prefix!r}, got {actual!r}"
    )


@then('the recorded published date is "{expected}"')
def step_recorded_published(context, expected):
    actual = context.extracted_article["published"]
    assert actual == expected, (
        f"Expected published {expected!r}, got {actual!r}"
    )


@then('the recorded updated date is "{expected}"')
def step_recorded_updated(context, expected):
    actual = context.extracted_article["updated"]
    assert actual == expected, (
        f"Expected updated {expected!r}, got {actual!r}"
    )


@then("the recorded published date equals the recorded updated date")
def step_recorded_published_equals_updated(context):
    published = context.extracted_article["published"]
    updated = context.extracted_article["updated"]
    assert published == updated, (
        f"Expected published == updated, got {published!r} != {updated!r}"
    )


@then('the recorded comment URLs in order are "{first}" then "{second}"')
def step_recorded_comment_urls_two(context, first, second):
    actual = context.extracted_urls
    expected = [first, second]
    assert actual == expected, (
        f"Expected comment URLs {expected!r}, got {actual!r}"
    )


@then("the recorded comment URLs in order are")
def step_recorded_comment_urls_table(context):
    """
    Verify extracted comment URLs match a single-column table.

    Each row in the table is one expected URL.  Behave strips leading and
    trailing whitespace from cell values automatically.

    Behave treats the first row of every DataTable as the column heading, so
    the first URL is recovered from context.table.headings[0] (the heading of
    column 0) and subsequent URLs from iterating the data rows.
    """
    # First row is the column heading in behave's Table model; data rows follow.
    expected = list(context.table.headings) + [row[0] for row in context.table]
    actual = context.extracted_urls
    assert actual == expected, (
        f"Expected comment URLs {expected!r}, got {actual!r}"
    )
