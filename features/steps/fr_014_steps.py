"""Step definitions for FR-014: Feed alternate link to the source GitHub repository."""

import os

from behave import then, when

import src.pipeline_feed


@when("the GitHub repo URL is constructed")
def step_construct_github_repo_url(context):
    """Call build_github_repo_url with the current GITHUB_REPOSITORY env var."""
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    context.github_repo_url = src.pipeline_feed.build_github_repo_url(
        github_repository
    )


@then('the GitHub repo URL is "{expected}"')
def step_github_repo_url_is(context, expected):
    assert context.github_repo_url == expected, (
        f"Expected GitHub repo URL {expected!r}, got {context.github_repo_url!r}"
    )
