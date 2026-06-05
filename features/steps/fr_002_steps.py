"""Step definitions for FR-002: Article inclusion filter with cascading code-URL search."""

import src.pipeline_feed
from behave import given, then, when


@given('an article has primary category "{category}"')
def step_article_primary_category(context, category):
    context.article_primary_category = category
    context.article_comment = None
    context.article_abstract = ""


@given('the article comment is "{comment}"')
def step_article_comment(context, comment):
    context.article_comment = comment


@given('the article comment element is "{element_state}"')
def step_article_comment_element_state(context, element_state):
    """Map the element state descriptor to the Python value passed to the filter.

    'absent' means the comment element did not appear in the API response (None).
    'empty' means the element was present but contained no text ("").
    """
    if element_state == "absent":
        context.article_comment = None
    elif element_state == "empty":
        context.article_comment = ""
    else:
        raise ValueError(f"Unexpected element_state: {element_state!r}")


@given('the accepted repo domains include "{domain}"')
def step_set_accepted_domains(context, domain):
    """Accumulate accepted repo domains for injection into the cascade."""
    if not hasattr(context, "accepted_repo_domains"):
        context.accepted_repo_domains = set()
    context.accepted_repo_domains.add(domain)


@given('the accepted repo domain suffixes include "{suffix}"')
def step_set_accepted_suffixes(context, suffix):
    """Accumulate accepted repo domain suffixes for injection into the cascade."""
    if not hasattr(context, "accepted_repo_suffixes"):
        context.accepted_repo_suffixes = set()
    context.accepted_repo_suffixes.add(suffix)


@given('the article abstract is "{abstract}"')
def step_article_abstract(context, abstract):
    context.article_abstract = abstract


@when("the inclusion filter is applied to the article")
def step_apply_inclusion_filter(context):
    """Build an Article, run the category check and enrichment cascade, then filter."""
    article = src.pipeline_feed.Article(
        title="",
        authors=[],
        primary_category=context.article_primary_category,
        abstract_url="",
        published="",
        updated="",
        abstract=getattr(context, "article_abstract", ""),
        comment=context.article_comment,
        comment_urls=src.pipeline_feed.extract_comment_urls(context.article_comment),
    )
    category_id = src.pipeline_feed.resolve_category_id()
    strict_mode = src.pipeline_feed.resolve_strict_mode()

    if not src.pipeline_feed.matches_category(article, category_id, strict_mode):
        context.article_included = False
        context.article_result = article
        return

    accepted_domains = (
        frozenset(context.accepted_repo_domains)
        if hasattr(context, "accepted_repo_domains")
        else None
    )
    accepted_suffixes = (
        frozenset(context.accepted_repo_suffixes)
        if hasattr(context, "accepted_repo_suffixes")
        else None
    )

    article = src.pipeline_feed.enrich_from_metadata(
        article,
        accepted_domains=accepted_domains,
        accepted_suffixes=accepted_suffixes,
    )
    context.article_result = article
    context.article_included = src.pipeline_feed.include_article(article)


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


@then('the article repo_found_in is "{expected}"')
def step_article_repo_found_in(context, expected):
    actual = context.article_result.repo_found_in
    assert actual == expected, (
        f"Expected repo_found_in {expected!r}, got {actual!r}"
    )
