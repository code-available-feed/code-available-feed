"""Step definitions for FR-017: Processed dict persistence."""

import datetime
import pathlib
import re
import tempfile
import xml.etree.ElementTree as ET

from behave import given, then, use_step_matcher, when

import src.pipeline_feed

_CAF_NS = src.pipeline_feed._CAF_NS
_ATOM_NS = src.pipeline_feed._ATOM_NS


def _minimal_article(
    abstract_url: str,
    published: str = "2026-06-01T00:00:00Z",
    comment_urls: list[str] | None = None,
) -> src.pipeline_feed.Article:
    """Build a minimal Article with the given abstract_url."""
    urls = comment_urls if comment_urls is not None else ["https://example.com/"]
    return src.pipeline_feed.Article(
        title="Test Article",
        authors=["Test Author"],
        primary_category="cs.AI",
        abstract_url=abstract_url,
        published=published,
        updated=published,
        abstract="",
        comment="https://example.com/" if urls else None,
        comment_urls=urls,
    )


def _build_atom_xml_with_processed(
    entries: list[src.pipeline_feed.Article],
    processed_rows: list[dict[str, str]],
) -> bytes:
    """Build atom.xml bytes containing entries and a processed element."""
    processed = {}
    for row in processed_rows:
        url = row["url"]
        repo_urls_str = row.get("repo_urls", "")
        repo_urls = tuple(repo_urls_str.split()) if repo_urls_str else ()
        processed[url] = src.pipeline_feed.ProcessedEntry(
            updated=row["updated"],
            repo_found_in=row.get("repo_found_in", ""),
            repo_urls=repo_urls,
        )
    return src.pipeline_feed.build_feed(
        entries,
        processed,
        category_id="cs.AI",
        strict_mode=False,
        github_repository="owner/code-available-feed",
    )


def _table_row_to_dict(row) -> dict[str, str]:
    """Convert a behave table Row to a dict."""
    return {heading: row[heading] for heading in row.headings}


# -- load_processed scenarios --


@given("no atom.xml file exists at the expected path")
def step_no_atom_xml(context):
    """Set up a temporary directory with no atom.xml."""
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    context.atom_xml_path = context.run_dir / "atom.xml"


@when("the processed dict is loaded")
def step_load_processed_default(context):
    """Load the processed dict with a wide date window."""
    context.loaded_processed = src.pipeline_feed.load_processed(
        context.atom_xml_path,
        start_date=datetime.date(2020, 1, 1),
        end_date=datetime.date(2030, 12, 31),
    )


@then("the processed dict is empty")
def step_processed_empty(context):
    assert context.loaded_processed == {}, (
        f"Expected empty processed dict, got {context.loaded_processed}"
    )


@given("an atom.xml file with entries but no processed element")
def step_atom_xml_no_processed(context):
    """Create an atom.xml with entries but no processed element."""
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    context.atom_xml_path = context.run_dir / "atom.xml"
    article = _minimal_article("https://arxiv.example.com/abs/0001v1")
    feed_bytes = src.pipeline_feed.build_feed(
        [article],
        {},
        category_id="cs.AI",
        strict_mode=False,
        github_repository="owner/code-available-feed",
    )
    context.atom_xml_path.write_bytes(feed_bytes)


@given("an atom.xml file with a processed element containing")
def step_atom_xml_with_processed(context):
    """Create an atom.xml with entries and a processed element from the table."""
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    context.atom_xml_path = context.run_dir / "atom.xml"
    rows = [_table_row_to_dict(row) for row in context.table]
    article = _minimal_article(
        "https://arxiv.example.com/abs/9999v1",
        published="2026-06-01T00:00:00Z",
    )
    feed_bytes = _build_atom_xml_with_processed([article], rows)
    context.atom_xml_path.write_bytes(feed_bytes)


@when('the processed dict is loaded with start date "{start}" and end date "{end}"')
def step_load_processed_with_dates(context, start, end):
    """Load the processed dict with specific date bounds."""
    start_date = datetime.date.fromisoformat(start)
    end_date = datetime.date.fromisoformat(end)
    context.loaded_processed = src.pipeline_feed.load_processed(
        context.atom_xml_path,
        start_date=start_date,
        end_date=end_date,
    )


@when("the processed dict is loaded without date bounds")
def step_load_processed_no_dates(context):
    """Load the processed dict with no date filter applied."""
    context.loaded_processed = src.pipeline_feed.load_processed(
        context.atom_xml_path,
    )


@then("the processed dict has {count:d} entries")
def step_processed_has_n_entries(context, count):
    assert len(context.loaded_processed) == count, (
        f"Expected {count} entries, got {len(context.loaded_processed)}: "
        f"{list(context.loaded_processed.keys())}"
    )


@then("the processed dict has {count:d} entry")
def step_processed_has_one_entry(context, count):
    assert len(context.loaded_processed) == count, (
        f"Expected {count} entry, got {len(context.loaded_processed)}: "
        f"{list(context.loaded_processed.keys())}"
    )


# Switch to regex matcher for steps that need to match empty strings
# between quotes (behave's default parse matcher requires non-empty values).
use_step_matcher("re")


@then(r'the entry for "(?P<url>[^"]+)" has repo_found_in "(?P<expected>[^"]*)"')
def step_entry_repo_found_in(context, url, expected):
    """Check repo_found_in for a specific entry in the loaded processed dict."""
    assert url in context.loaded_processed, (
        f"URL {url!r} not found in processed dict. "
        f"Keys: {list(context.loaded_processed.keys())}"
    )
    actual = context.loaded_processed[url].repo_found_in
    assert actual == expected, (
        f"Expected repo_found_in {expected!r} for {url}, got {actual!r}"
    )


@given(r'a processed dict entry for "(?P<url>[^"]+)" with repo_found_in "(?P<found_in>[^"]*)" and repo_urls "(?P<urls>[^"]*)"')
def step_processed_entry(context, url, found_in, urls):
    """Store a processed dict entry for later application."""
    if not hasattr(context, "test_processed"):
        context.test_processed = {}
    repo_urls = tuple(urls.split()) if urls else ()
    context.test_processed[url] = src.pipeline_feed.ProcessedEntry(
        updated="2026-06-01T00:00:00Z",
        repo_found_in=found_in,
        repo_urls=repo_urls,
    )


# Switch back to default parse matcher for remaining steps.
use_step_matcher("parse")


@given('an article fetched from the API with abstract_url "{url}"')
def step_api_article(context, url):
    """Create a minimal article as if fetched from the API (no enrichment yet)."""
    context.test_article = src.pipeline_feed.Article(
        title="Test Article",
        authors=["Test Author"],
        primary_category="cs.AI",
        abstract_url=url,
        published="2026-06-01T00:00:00Z",
        updated="2026-06-01T00:00:00Z",
        abstract="",
        comment=None,
        comment_urls=[],
    )
    context.enrichment_ran = False


@when("the pipeline applies the processed dict to the article")
def step_apply_processed(context):
    """Apply the processed dict to the article, mirroring main()'s restore logic.

    Stores the result in context.article_result (for fr_002's
    'the article repo_found_in is' step) and context.enrichment_result
    (for fr_016's 'the article repo_urls contains' step).
    """
    url = context.test_article.abstract_url
    if url in context.test_processed:
        entry = context.test_processed[url]
        result = context.test_article._replace(
            repo_found_in=entry.repo_found_in,
            repo_urls=entry.repo_urls,
        )
        context.enrichment_ran = False
    else:
        result = src.pipeline_feed.enrich_from_metadata(
            context.test_article
        )
        context.enrichment_ran = True
    context.article_result = result
    context.enrichment_result = result


@then("the article has empty repo_found_in")
def step_article_empty_repo_found_in(context):
    actual = context.article_result.repo_found_in
    assert actual == "", (
        f"Expected empty repo_found_in, got {actual!r}"
    )


@then("no enrichment cascade runs for this article")
def step_no_enrichment(context):
    assert not context.enrichment_ran, (
        "Expected no enrichment cascade to run, but it did"
    )


# -- build_feed processed element scenarios --


@given("a list of filtered articles with repo_found_in set")
def step_filtered_articles(context):
    """Create articles with repo_found_in populated."""
    context.articles = [
        _minimal_article("https://arxiv.example.com/abs/0001v1")._replace(
            repo_found_in="comment",
            repo_urls=("https://example.com/",),
        ),
    ]


@given("a processed dict with {count:d} entries")
def step_processed_dict_n(context, count):
    """Create a processed dict with n entries."""
    context.test_processed = {}
    for i in range(1, count + 1):
        url = f"https://arxiv.example.com/abs/{i:04d}v1"
        context.test_processed[url] = src.pipeline_feed.ProcessedEntry(
            updated="2026-06-01T00:00:00Z",
            repo_found_in="comment" if i == 1 else "",
            repo_urls=("https://example.com/",) if i == 1 else (),
        )


@given("a processed dict with {count:d} entry")
def step_processed_dict_one(context, count):
    """Create a processed dict with one entry."""
    step_processed_dict_n(context, count)


@when("build_feed is called with the articles and processed dict")
def step_build_feed_with_processed(context):
    """Call build_feed with articles and processed dict."""
    context.feed_bytes = src.pipeline_feed.build_feed(
        context.articles,
        context.test_processed,
        category_id="cs.AI",
        strict_mode=False,
        github_repository="owner/code-available-feed",
    )
    context.feed_root = ET.fromstring(context.feed_bytes)


@then('the generated atom.xml contains a "code-available-feed:processed" element')
def step_has_processed_element(context):
    processed_elem = context.feed_root.find(f"{{{_CAF_NS}}}processed")
    assert processed_elem is not None, (
        "Expected <code-available-feed:processed> element in feed, but not found"
    )


@then('the processed element has {count:d} child "code-available-feed:article" elements')
def step_processed_child_count(context, count):
    processed_elem = context.feed_root.find(f"{{{_CAF_NS}}}processed")
    assert processed_elem is not None, "No processed element found"
    children = processed_elem.findall(f"{{{_CAF_NS}}}article")
    assert len(children) == count, (
        f"Expected {count} article children, got {len(children)}"
    )


# -- Processed element sorting scenario --


@given('a processed dict with entries for "{url1}" and "{url2}"')
def step_processed_dict_two_urls(context, url1, url2):
    """Create a processed dict with two specific URLs (in the given order)."""
    context.test_processed = {}
    context.test_processed[url1] = src.pipeline_feed.ProcessedEntry(
        updated="2026-06-01T00:00:00Z",
        repo_found_in="comment",
        repo_urls=("https://example.com/",),
    )
    context.test_processed[url2] = src.pipeline_feed.ProcessedEntry(
        updated="2026-06-02T00:00:00Z",
        repo_found_in="abstract",
        repo_urls=("https://example.com/other",),
    )
    context.articles = [
        _minimal_article(url1)._replace(
            repo_found_in="comment", repo_urls=("https://example.com/",)
        ),
    ]


@when("build_feed is called with the processed dict")
def step_build_feed_with_dict(context):
    """Call build_feed with the processed dict."""
    context.feed_bytes = src.pipeline_feed.build_feed(
        context.articles,
        context.test_processed,
        category_id="cs.AI",
        strict_mode=False,
        github_repository="owner/code-available-feed",
    )
    context.feed_root = ET.fromstring(context.feed_bytes)


@then('the first processed child has url "{expected_url}"')
def step_first_processed_url(context, expected_url):
    processed_elem = context.feed_root.find(f"{{{_CAF_NS}}}processed")
    children = processed_elem.findall(f"{{{_CAF_NS}}}article")
    assert len(children) >= 1, "No processed children found"
    actual = children[0].get("url")
    assert actual == expected_url, (
        f"Expected first child url {expected_url!r}, got {actual!r}"
    )


@then('the second processed child has url "{expected_url}"')
def step_second_processed_url(context, expected_url):
    processed_elem = context.feed_root.find(f"{{{_CAF_NS}}}processed")
    children = processed_elem.findall(f"{{{_CAF_NS}}}article")
    assert len(children) >= 2, f"Expected at least 2 children, got {len(children)}"
    actual = children[1].get("url")
    assert actual == expected_url, (
        f"Expected second child url {expected_url!r}, got {actual!r}"
    )


# -- write_processed_element scenarios --


@given('an atom.xml file with {n_entries:d} feed entries and a processed element with {n_processed:d} entry')
def step_atom_xml_with_entries_and_processed(context, n_entries, n_processed):
    """Create an atom.xml with the specified number of entries and processed children."""
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    context.atom_xml_path = context.run_dir / "atom.xml"

    articles = []
    for i in range(1, n_entries + 1):
        articles.append(_minimal_article(
            f"https://arxiv.example.com/abs/{i:04d}v1",
            published=f"2026-06-{i:02d}T00:00:00Z",
        ))

    processed_rows = []
    for i in range(1, n_processed + 1):
        processed_rows.append({
            "url": f"https://arxiv.example.com/abs/p{i:04d}v1",
            "updated": f"2026-06-{i:02d}T00:00:00Z",
            "repo_found_in": "comment",
            "repo_urls": "https://example.com/",
        })

    feed_bytes = _build_atom_xml_with_processed(articles, processed_rows)
    context.atom_xml_path.write_bytes(feed_bytes)


@given("an updated processed dict with {count:d} entries")
def step_updated_processed_dict(context, count):
    """Create a new processed dict with count entries for write_processed_element."""
    context.test_processed = {}
    for i in range(1, count + 1):
        url = f"https://arxiv.example.com/abs/new{i:04d}v1"
        context.test_processed[url] = src.pipeline_feed.ProcessedEntry(
            updated=f"2026-06-{i:02d}T00:00:00Z",
            repo_found_in="comment" if i == 1 else "abstract",
            repo_urls=(f"https://example.com/repo{i}",),
        )


@when("write_processed_element is called")
def step_call_write_processed(context):
    """Call write_processed_element with the test processed dict."""
    src.pipeline_feed.write_processed_element(
        context.atom_xml_path,
        context.test_processed,
    )


@then("the atom.xml still has {count:d} feed entries")
def step_atom_xml_entry_count(context, count):
    tree = ET.parse(context.atom_xml_path)
    root = tree.getroot()
    entries = root.findall(f"{{{_ATOM_NS}}}entry")
    assert len(entries) == count, (
        f"Expected {count} entries, got {len(entries)}"
    )


@then("the processed element now has {count:d} child elements")
def step_processed_now_has_n(context, count):
    tree = ET.parse(context.atom_xml_path)
    root = tree.getroot()
    processed_elem = root.find(f"{{{_CAF_NS}}}processed")
    assert processed_elem is not None, "No processed element found"
    children = processed_elem.findall(f"{{{_CAF_NS}}}article")
    assert len(children) == count, (
        f"Expected {count} processed children, got {len(children)}"
    )


@then("no atom.xml file is created")
def step_no_atom_created(context):
    assert not context.atom_xml_path.exists(), (
        f"Expected no atom.xml at {context.atom_xml_path}, but it exists"
    )
