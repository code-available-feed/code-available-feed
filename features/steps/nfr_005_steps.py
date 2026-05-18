"""Step definitions for NFR-005: Byte-for-byte deterministic XML output."""

import hashlib
import json
import os
import pathlib

from behave import given, then, when

import src.pipeline_feed
import src.utils


def _run_feed_and_write(context, path: str) -> None:
    """Call build_feed with context.articles and write the bytes to path."""
    category_id = src.utils.resolve_category_id()
    strict_mode = src.utils.resolve_strict_mode()
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    feed_bytes = src.pipeline_feed.build_feed(
        context.articles, category_id, strict_mode, github_repository
    )
    dest = pathlib.Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(feed_bytes)
    context.feed_bytes = feed_bytes


@given('a fixed set of input articles loaded from "{json_path}"')
def step_load_articles_from_json(context, json_path: str) -> None:
    """Load the article list from a JSON fixture file into context.articles."""
    context.articles = json.loads(
        pathlib.Path(json_path).read_text(encoding="utf-8")
    )


@given("any non-empty input article set")
def step_any_nonempty_article_set(context) -> None:
    """Provide a single article with valid field values."""
    context.articles = [
        {
            "title": "Any Paper",
            "authors": ["Test Author"],
            "primary_category": "cs.AI",
            "abstract_url": "https://arxiv.org/abs/0000.00000v1",
            "published": "2026-05-12T11:30:00Z",
            "updated": "2026-05-12T11:30:00Z",
            "comment": "Code: https://example.com/",
            "comment_urls": ["https://example.com/"],
        }
    ]


@when('the feed generator runs and writes to "{path}"')
def step_feed_generator_runs_and_writes(context, path: str) -> None:
    """Generate the feed and write the bytes to the given path."""
    _run_feed_and_write(context, path)


@when('the feed generator runs again and writes to "{path}"')
def step_feed_generator_runs_again_and_writes(context, path: str) -> None:
    """Generate the feed a second time and write the bytes to the given path."""
    _run_feed_and_write(context, path)


@when("the same input articles are shuffled into a different order")
def step_shuffle_articles(context) -> None:
    """Reverse context.articles to produce an order that differs from the original."""
    context.articles = list(reversed(context.articles))


@when("the feed generator runs")
def step_feed_generator_runs(context) -> None:
    """Generate the feed from context.articles and store the bytes in context.feed_bytes."""
    category_id = src.utils.resolve_category_id()
    strict_mode = src.utils.resolve_strict_mode()
    github_repository = os.environ.get("GITHUB_REPOSITORY", "")
    context.feed_bytes = src.pipeline_feed.build_feed(
        context.articles, category_id, strict_mode, github_repository
    )


@then('the SHA-256 hash of "{path_a}" equals the SHA-256 hash of "{path_b}"')
def step_sha256_equal(context, path_a: str, path_b: str) -> None:
    """Assert that the two files have identical SHA-256 hashes."""
    hash_a = hashlib.sha256(pathlib.Path(path_a).read_bytes()).hexdigest()
    hash_b = hashlib.sha256(pathlib.Path(path_b).read_bytes()).hexdigest()
    assert hash_a == hash_b, (
        f"SHA-256 mismatch: {path_a!r} -> {hash_a}, {path_b!r} -> {hash_b}"
    )


@then('the first line of the output equals "{expected}"')
def step_first_line_equals(context, expected: str) -> None:
    """Assert that the first line of context.feed_bytes matches expected."""
    first_line = context.feed_bytes.decode("utf-8").split("\n")[0]
    assert first_line == expected, (
        f"Expected first line {expected!r}, got {first_line!r}"
    )
