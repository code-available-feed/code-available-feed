"""Step definitions for NFR-004: Atom XML output is valid RFC 4287 and properly escaped."""

import xml.etree.ElementTree as ET

from behave import given, then


@given('one input article with title "{title}"')
def step_one_article_with_title(context, title):
    """Provide a single article with the given title and minimal valid other fields."""
    context.articles = [
        {
            "title": title,
            "authors": ["Test Author"],
            "primary_category": "cs.AI",
            "abstract_url": "https://arxiv.org/abs/0000.00000v1",
            "published": "2026-05-12T11:30:00Z",
            "updated": "2026-05-12T11:30:00Z",
            "comment_urls": ["https://example.com/"],
        }
    ]


@given('one input article with abstract URL "{abstract_url}"')
def step_one_article_with_abstract_url(context, abstract_url):
    """Provide a single article with the given abstract URL; comment_urls start empty."""
    context.articles = [
        {
            "title": "Any Paper Title",
            "authors": ["Test Author"],
            "primary_category": "cs.AI",
            "abstract_url": abstract_url,
            "published": "2026-05-12T11:30:00Z",
            "updated": "2026-05-12T11:30:00Z",
            "comment_urls": [],
        }
    ]


@given('the article has comment URL "{comment_url}"')
def step_article_has_comment_url(context, comment_url):
    """Append comment_url to the comment_urls list of the first article in context."""
    context.articles[0]["comment_urls"].append(comment_url)


@then('the raw output bytes contain the substring "{substring}"')
def step_raw_bytes_contain(context, substring):
    expected = substring.encode("utf-8")
    assert expected in context.feed_bytes, (
        f"Expected {substring!r} in raw output bytes"
    )


@then('the raw output bytes do not contain the substring "{substring}"')
def step_raw_bytes_not_contain(context, substring):
    expected = substring.encode("utf-8")
    assert expected not in context.feed_bytes, (
        f"Unexpected {substring!r} found in raw output bytes"
    )


@then(
    'the raw output bytes contain the substring "{substring}"'
    ' inside a content element'
)
def step_raw_bytes_contain_in_content(context, substring):
    # Search the raw (pre-parse) bytes between <content type="text"> and
    # </content> so that the caller can assert on the XML-escaped form
    # (e.g. "&amp;" rather than "&") without round-tripping through a parser
    # that would unescape it.
    raw = context.feed_bytes
    open_tag = b'<content type="text">'
    close_tag = b"</content>"
    idx = raw.find(open_tag)
    assert idx >= 0, 'No <content type="text"> element found in raw output bytes'
    end = raw.find(close_tag, idx)
    assert end >= 0, "No </content> closing tag found after content open tag"
    inner = raw[idx + len(open_tag) : end]
    expected = substring.encode("utf-8")
    assert expected in inner, (
        f"Expected {substring!r} inside content element, got {inner!r}"
    )


@then(
    "the raw output bytes can be parsed by xml.etree.ElementTree"
    " without raising an exception"
)
def step_raw_bytes_parseable(context):
    try:
        ET.fromstring(context.feed_bytes)
    except ET.ParseError as exc:
        assert False, f"xml.etree.ElementTree raised ParseError: {exc}"
