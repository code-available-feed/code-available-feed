"""Step definitions for FR-016: PDF body URL extraction."""

import io
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
            page["/Annots"].append(annot_ref)

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


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("PDF repo URLs are extracted")
def step_extract_pdf_urls(context):
    pdf_bytes = _build_test_pdf(context.pdf_pages)
    _save_debug_pdf(context, pdf_bytes)

    context.extracted_urls = src.pipeline_feed.extract_pdf_repo_urls(
        pdf_bytes,
        accepted_domains=_get_accepted_domains(context),
        accepted_suffixes=_get_accepted_suffixes(context),
    )


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
