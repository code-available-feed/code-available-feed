"""Step definitions for FR-016: PDF body URL extraction."""

import contextlib
import io
import json
import pathlib
import typing

import src.pipeline_feed
from behave import given, then, when
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


def _ensure_pdf_pages(context: typing.Any, page_num: int) -> None:
    """Grow context.pdf_pages so index page_num-1 exists."""
    if not hasattr(context, "pdf_pages"):
        context.pdf_pages = []
    while len(context.pdf_pages) < page_num:
        context.pdf_pages.append({"lines": [], "annotations": []})


def _escape_pdf_string(text: str) -> str:
    """Escape characters special in PDF literal strings."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_test_pdf(pages: list[dict[str, typing.Any]]) -> bytes:
    """Build a minimal PDF from page specifications for testing.

    Each page dict has:
    - "lines": list[str] -- text lines rendered top to bottom.
    - "annotations": list[str] -- URIs for /Link annotations.
    """
    writer = PdfWriter()

    for page_index, page_spec in enumerate(pages):
        page = writer.add_blank_page(612, 792)
        lines = page_spec.get("lines", [])
        annotation_uris = page_spec.get("annotations", [])

        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): font_ref,
            })
        })

        if lines:
            parts = ["BT", "/F1 12 Tf", "72 720 Td"]
            for line_index, line in enumerate(lines):
                if line_index > 0:
                    parts.append("0 -14 Td")
                parts.append(f"({_escape_pdf_string(line)}) Tj")
            parts.append("ET")
            content_bytes = "\n".join(parts).encode()
            stream = DecodedStreamObject()
            stream.set_data(content_bytes)
            page[NameObject("/Contents")] = writer._add_object(stream)

        for uri in annotation_uris:
            link_annot = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject([
                    NumberObject(72), NumberObject(700),
                    NumberObject(400), NumberObject(720),
                ]),
                NameObject("/A"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Action"),
                    NameObject("/S"): NameObject("/URI"),
                    NameObject("/URI"): TextStringObject(uri),
                }),
            })
            annot_ref = writer._add_object(link_annot)
            if "/Annots" not in page:
                page[NameObject("/Annots")] = ArrayObject()
            annots = typing.cast(ArrayObject, page["/Annots"])
            annots.append(annot_ref)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _save_debug_pdf(context: typing.Any, pdf_bytes: bytes) -> None:
    """Save generated PDF to features/fixtures/pdfs/ for debugging."""
    fixture_dir = pathlib.Path("features/fixtures/pdfs")
    fixture_dir.mkdir(parents=True, exist_ok=True)
    safe_name = context.scenario.name.replace(" ", "_")[:80]
    fixture_dir.joinpath(f"{safe_name}.pdf").write_bytes(pdf_bytes)


def _get_accepted_domains(context: typing.Any) -> frozenset[str] | None:
    """Return injected accepted domains or None for module defaults."""
    if hasattr(context, "accepted_repo_domains") and context.accepted_repo_domains:
        return frozenset(context.accepted_repo_domains)
    return None


def _get_accepted_suffixes(context: typing.Any) -> frozenset[str] | None:
    """Return injected accepted suffixes or None for module defaults."""
    if hasattr(context, "accepted_repo_suffixes") and context.accepted_repo_suffixes:
        return frozenset(context.accepted_repo_suffixes)
    return None


# ---------------------------------------------------------------------------
# Given steps: PDF page construction
# ---------------------------------------------------------------------------


@given('a PDF whose page {page_num:d} has a link annotation with URI "{uri}"')
def step_pdf_page_annotation(context, page_num, uri):
    _ensure_pdf_pages(context, page_num)
    context.pdf_pages[page_num - 1]["annotations"].append(uri)


@given('a PDF whose page {page_num:d} contains the text "{text}"')
def step_pdf_page_text(context, page_num, text):
    _ensure_pdf_pages(context, page_num)
    context.pdf_pages[page_num - 1]["lines"].append(text)


@given('the same PDF page {page_num:d} contains the text "{text}"')
def step_pdf_same_page_text(context, page_num, text):
    context.pdf_pages[page_num - 1]["lines"].append(text)


@given('the PDF page {page_num:d} starts with the line "{line}"')
def step_pdf_page_starts_with(context, page_num, line):
    _ensure_pdf_pages(context, page_num)
    context.pdf_pages[page_num - 1]["lines"].insert(0, line)


@given('the PDF page {page_num:d} contains the text "{text}"')
def step_pdf_page_contains_text(context, page_num, text):
    _ensure_pdf_pages(context, page_num)
    context.pdf_pages[page_num - 1]["lines"].append(text)


# ---------------------------------------------------------------------------
# Given steps: enrichment scenarios
# ---------------------------------------------------------------------------


@given("an article that has not been enriched")
def step_unenriched_article(context):
    context.test_article = src.pipeline_feed.Article(
        title="Test Article",
        authors=["Author One"],
        primary_category="cs.AI",
        abstract_url="https://arxiv.example.com/abs/0000.00001v1",
        published="2026-06-01T00:00:00Z",
        updated="2026-06-01T00:00:00Z",
        abstract="",
        comment=None,
        comment_urls=[],
    )


@given("the PDF bytes for the article are invalid")
def step_invalid_pdf_bytes(context):
    context.pdf_bytes_for_article = b"not a valid PDF"


@given('an article with repo_found_in "{value}"')
def step_already_enriched_article(context, value):
    context.test_article = src.pipeline_feed.Article(
        title="Test Article",
        authors=["Author One"],
        primary_category="cs.AI",
        abstract_url="https://arxiv.example.com/abs/0000.00001v1",
        published="2026-06-01T00:00:00Z",
        updated="2026-06-01T00:00:00Z",
        abstract="",
        comment="Code at https://code.example.com/repo",
        comment_urls=["https://code.example.com/repo"],
        repo_found_in=value,
        repo_urls=("https://code.example.com/repo",),
    )


@given('the PDF for the article contains "{url}" on page {page_num:d}')
def step_pdf_for_article_with_url(context, url, page_num):
    """Build a test PDF with the given URL as text on the specified page."""
    pages: list[dict[str, typing.Any]] = []
    while len(pages) < page_num:
        pages.append({"lines": [], "annotations": []})
    pages[page_num - 1]["lines"].append(url)
    context.pdf_bytes_for_article = _build_test_pdf(pages)


@given("the PDF for the article has no code URLs")
def step_pdf_for_article_no_code_urls(context):
    """Build a one-page test PDF whose text contains no accepted-domain URLs."""
    context.pdf_bytes_for_article = _build_test_pdf([
        {"lines": ["Abstract: plain text without any code-hosting URLs."], "annotations": []}
    ])


@given("the enrichment PDF is built from the page specifications")
def step_build_enrichment_pdf_from_pages(context):
    """Convert context.pdf_pages (built by page-spec given steps) to context.pdf_bytes_for_article.

    Allows enrichment scenarios to reuse the page-building steps
    (e.g. 'a PDF whose page N contains the text') that normally target
    extract_pdf_repo_urls, and then redirect the result to enrich_from_pdf.
    """
    pdf_bytes = _build_test_pdf(context.pdf_pages)
    _save_debug_pdf(context, pdf_bytes)
    context.pdf_bytes_for_article = pdf_bytes


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("PDF repo URLs are extracted")
def step_extract_pdf_urls(context):
    pdf_bytes = _build_test_pdf(context.pdf_pages)
    _save_debug_pdf(context, pdf_bytes)

    urls, _contexts = src.pipeline_feed.extract_pdf_repo_urls(
        pdf_bytes,
        accepted_domains=_get_accepted_domains(context),
        accepted_suffixes=_get_accepted_suffixes(context),
    )
    context.extracted_urls = urls


@when("PDF repo URLs are extracted with log capture")
def step_extract_pdf_urls_with_log_capture(context):
    """Run extract_pdf_repo_urls and capture the returned context strings.

    context.extracted_urls[i] and context.extracted_contexts[i] are parallel:
    extracted_contexts[i] is the "pN: surrounding text" string for that URL.
    """
    pdf_bytes = _build_test_pdf(context.pdf_pages)
    _save_debug_pdf(context, pdf_bytes)

    urls, contexts = src.pipeline_feed.extract_pdf_repo_urls(
        pdf_bytes,
        accepted_domains=_get_accepted_domains(context),
        accepted_suffixes=_get_accepted_suffixes(context),
    )
    context.extracted_urls = urls
    context.extracted_contexts = contexts


@when("PDF enrichment is attempted for the article")
def step_attempt_pdf_enrichment(context):
    pdf_bytes = getattr(context, "pdf_bytes_for_article", None)

    def fetch_pdf(url: str) -> bytes:
        if pdf_bytes is None:
            raise RuntimeError("No PDF bytes prepared for test")
        return pdf_bytes

    result = src.pipeline_feed.enrich_from_pdf(
        context.test_article,
        accepted_domains=_get_accepted_domains(context),
        accepted_suffixes=_get_accepted_suffixes(context),
        _fetch_pdf=fetch_pdf,
    )
    context.enrichment_result = result
    if result is not None:
        context.article_result = result


@when("PDF enrichment is attempted with log capture")
def step_attempt_pdf_enrichment_with_log_capture(context):
    """Run enrich_from_pdf with JSON logging active and capture stdout.

    context.captured_pdf_log holds the raw JSON log lines emitted during the
    call.  Use "the enrichment log contains a message containing" steps to
    assert on individual fields.
    """
    pdf_bytes = getattr(context, "pdf_bytes_for_article", None)

    def fetch_pdf(url: str) -> bytes:
        if pdf_bytes is None:
            raise RuntimeError("No PDF bytes prepared for test")
        return pdf_bytes

    stdout_buf = io.StringIO()
    # redirect_stdout must wrap _setup_logging() so the StreamHandler binds to
    # the StringIO buffer rather than the real stdout at handler-creation time.
    with contextlib.redirect_stdout(stdout_buf):
        src.pipeline_feed._setup_logging()
        result = src.pipeline_feed.enrich_from_pdf(
            context.test_article,
            accepted_domains=_get_accepted_domains(context),
            accepted_suffixes=_get_accepted_suffixes(context),
            _fetch_pdf=fetch_pdf,
        )
    context.enrichment_result = result
    if result is not None:
        context.article_result = result
    context.captured_pdf_log = stdout_buf.getvalue()


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then('the extracted URLs contain "{url}"')
def step_urls_contain(context, url):
    assert url in context.extracted_urls, (
        f"Expected {url!r} in extracted URLs, got {context.extracted_urls!r}"
    )


@then('the extracted URLs do not contain "{url}"')
def step_urls_not_contain(context, url):
    assert url not in context.extracted_urls, (
        f"Expected {url!r} NOT in extracted URLs, but it was present"
    )


@then("the extracted URLs are empty")
def step_urls_empty(context):
    assert len(context.extracted_urls) == 0, (
        f"Expected empty URL list, got {context.extracted_urls!r}"
    )


@then("the extracted URLs contain exactly {count:d} entry")
def step_urls_exact_count(context, count):
    actual = len(context.extracted_urls)
    assert actual == count, (
        f"Expected {count} URL(s), got {actual}: {context.extracted_urls!r}"
    )


@then("the enrichment result is None")
def step_result_is_none(context):
    assert context.enrichment_result is None, (
        f"Expected None, got {context.enrichment_result!r}"
    )


@then("the article is returned unchanged")
def step_article_unchanged(context):
    assert context.enrichment_result == context.test_article, (
        f"Expected article unchanged, got repo_found_in="
        f"{context.enrichment_result.repo_found_in!r}"
    )


@then('the article repo_urls contains "{url}"')
def step_repo_urls_contains(context, url):
    result = context.enrichment_result
    assert url in result.repo_urls, (
        f"Expected {url!r} in repo_urls, got {result.repo_urls!r}"
    )


@then('the enrichment log contains a message containing "{text}"')
def step_enrichment_log_contains(context, text):
    """Assert a JSON log line from enrich_from_pdf has a message containing text."""
    lines = context.captured_pdf_log.splitlines()
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if text in obj.get("message", ""):
            return
    assert False, (
        f"No enrichment log line has message containing {text!r}\n"
        f"Captured log:\n{context.captured_pdf_log}"
    )


@then('the enrichment log contains a message containing all of "{text1}" and "{text2}"')
def step_enrichment_log_contains_all(context, text1, text2):
    """Assert a JSON log line from enrich_from_pdf has a message containing both text1 and text2."""
    lines = context.captured_pdf_log.splitlines()
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", "")
        if text1 in msg and text2 in msg:
            return
    assert False, (
        f"No enrichment log line has message containing both {text1!r} and {text2!r}\n"
        f"Captured log:\n{context.captured_pdf_log}"
    )


@then("the enrichment log contains a message containing all substrings")
def step_enrichment_log_contains_all_substrings_table(context):
    """Assert that a single JSON log line from enrich_from_pdf contains all substrings in the table.

    Each table row supplies one required substring.
    This step exists to allow assertions that contain double-quote characters,
    which cannot appear inside the Gherkin step string delimiters used by
    step_enrichment_log_contains_all.
    """
    substrings = [row[0] for row in context.table]
    lines = context.captured_pdf_log.splitlines()
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", "")
        if all(s in msg for s in substrings):
            return
    assert False, (
        f"No enrichment log line has message containing all of {substrings!r}\n"
        f"Captured log:\n{context.captured_pdf_log}"
    )


@then('the captured log context for "{url}" contains "{text}"')
def step_captured_log_context_contains(context, url, text):
    """Assert the context string returned by extract_pdf_repo_urls for url contains text.

    context.extracted_urls and context.extracted_contexts are parallel lists
    produced by the "PDF repo URLs are extracted with log capture" step.
    """
    try:
        idx = context.extracted_urls.index(url)
    except ValueError:
        assert False, (
            f"URL {url!r} not found in extracted URLs: {context.extracted_urls!r}"
        )
    context_str = context.extracted_contexts[idx]
    assert text in context_str, (
        f"Expected {text!r} in context for {url!r}, got {context_str!r}"
    )
