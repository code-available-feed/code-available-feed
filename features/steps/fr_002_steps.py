"""Step definitions for FR-002: Article inclusion filter."""

import src.pipeline_feed
from behave import given, then, when


@given('an article has primary category "{category}"')
def step_article_primary_category(context, category):
    context.article_primary_category = category
    # Initialize comment to absent; a subsequent step overwrites it when set.
    context.article_comment = None


@given('the article comment is "{comment}"')
def step_article_comment(context, comment):
    context.article_comment = comment


@given('the article comment element is "{element_state}"')
def step_article_comment_element_state(context, element_state):
    """
    Map the element state descriptor to the Python value passed to include_article.
    'absent' means the comment element did not appear in the API response (None).
    'empty' means the element was present but contained no text ("").
    """
    if element_state == "absent":
        context.article_comment = None
    elif element_state == "empty":
        context.article_comment = ""
    else:
        raise ValueError(f"Unexpected element_state: {element_state!r}")


@when("the inclusion filter is applied to the article")
def step_apply_inclusion_filter(context):
    """Build an Article with only the fields the filter inspects and call include_article."""
    article = src.pipeline_feed.Article(
        title="",
        authors=[],
        primary_category=context.article_primary_category,
        abstract_url="",
        published="",
        updated="",
        comment=context.article_comment,
        comment_urls=src.pipeline_feed.extract_comment_urls(context.article_comment),
    )
    context.article_included = src.pipeline_feed.include_article(
        article,
        src.pipeline_feed.resolve_category_id(),
        src.pipeline_feed.resolve_strict_mode(),
    )


@then("the article is included")
def step_article_is_included(context):
    assert context.article_included, (
        "Expected article to be included, but it was excluded"
    )


@then("the article is excluded")
def step_article_is_excluded(context):
    assert not context.article_included, (
        "Expected article to be excluded, but it was included"
    )
