@status-done
Feature: FR-016 PDF body URL extraction

  The pipeline extracts accepted-domain URLs from the PDF body (up to the
  References section) as a third source of code links in the cascade.
  Three extraction layers are applied per page in order: link annotations
  (primary), https:// text regex (fallback 1), and bare domain text regex
  (fallback 2).
  Scanning stops before the References section to avoid false positives from
  cited URLs.
  All extracted URLs are filtered to the accepted domain set and deduplicated.

  The accepted domain set is injectable in tests via a parameter so scenarios
  use example.com subdomains instead of real code-hosting domains.

  Test PDFs are generated on-the-fly by step definitions using pypdf and
  saved to features/fixtures/pdfs/ for human debugging of test failures.

  Scenario: URL found via PDF link annotation on accepted domain
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 has a link annotation with URI "https://code.example.com/user/repo"
    When PDF repo URLs are extracted
    Then the extracted URLs contain "https://code.example.com/user/repo"

  Scenario: URL found via text https regex on accepted domain
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 contains the text "Code: https://code.example.com/user/repo"
    When PDF repo URLs are extracted
    Then the extracted URLs contain "https://code.example.com/user/repo"

  Scenario: Bare domain URL without https scheme found via text regex
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 contains the text "Code: code.example.com/user/repo"
    When PDF repo URLs are extracted
    Then the extracted URLs contain "https://code.example.com/user/repo"

  Scenario: URL after References section heading is not extracted
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 contains the text "Code: https://code.example.com/user/repo"
    And the PDF page 2 starts with the line "References"
    And the PDF page 2 contains the text "https://code.example.com/cited/tool"
    When PDF repo URLs are extracted
    Then the extracted URLs contain "https://code.example.com/user/repo"
    And the extracted URLs do not contain "https://code.example.com/cited/tool"

  Scenario: URL on non-accepted domain in PDF is filtered out
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 contains the text "See https://journal.example.org/paper"
    When PDF repo URLs are extracted
    Then the extracted URLs are empty

  Scenario: Wildcard domain suffix match works in PDF extraction
    Given the accepted repo domain suffixes include ".pages.example.com"
    And a PDF whose page 1 has a link annotation with URI "https://user.pages.example.com/project"
    When PDF repo URLs are extracted
    Then the extracted URLs contain "https://user.pages.example.com/project"

  Scenario: Duplicate URLs across extraction layers are deduplicated
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 has a link annotation with URI "https://code.example.com/user/repo"
    And the same PDF page 1 contains the text "https://code.example.com/user/repo"
    When PDF repo URLs are extracted
    Then the extracted URLs contain exactly 1 entry

  Scenario: Footnote-prepended URL token has context logged
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 contains the text "context before 2https://code.example.com/user/repo context after"
    When PDF repo URLs are extracted with log capture
    Then the captured log context for "https://code.example.com/user/repo" contains "context before"

  Scenario: Annotation-only URL uses anchor text as context
    Given the accepted repo domains include "code.example.com"
    And a PDF whose page 1 has a link annotation with URI "https://code.example.com/user/repo"
    And the same PDF page 1 contains the text "our code"
    When PDF repo URLs are extracted with log capture
    Then the captured log context for "https://code.example.com/user/repo" contains "our code"

  Scenario: Corrupt PDF bytes return None from enrichment
    Given the accepted repo domains include "code.example.com"
    And an article that has not been enriched
    And the PDF bytes for the article are invalid
    When PDF enrichment is attempted for the article
    Then the enrichment result is None

  Scenario: enrich_from_pdf skips articles already enriched from metadata
    Given the accepted repo domains include "code.example.com"
    And an article with repo_found_in "comment"
    When PDF enrichment is attempted for the article
    Then the article is returned unchanged

  Scenario: PDF repo_found_in is "pdf" when URL found only in PDF body
    Given the accepted repo domains include "code.example.com"
    And an article that has not been enriched
    And the PDF for the article contains "https://code.example.com/user/repo" on page 1
    When PDF enrichment is attempted for the article
    Then the article repo_found_in is "pdf"
    And the article repo_urls contains "https://code.example.com/user/repo"

  # --- PDF enrichment log format scenarios ---

  Scenario: PDF enrichment emits pdf_fetching, pdf_fetched, and pdf log lines when a URL is found
    Given the accepted repo domains include "code.example.com"
    And an article that has not been enriched
    And the PDF for the article contains "https://code.example.com/user/repo" on page 1
    When PDF enrichment is attempted with log capture
    Then the enrichment log contains a message containing all of "origin=new status=pdf_fetching" and "url=https://arxiv.example.com/abs/0000.00001v1"
    And the enrichment log contains a message containing all of "origin=new status=pdf_fetched pages=1" and "url=https://arxiv.example.com/abs/0000.00001v1"
    And the enrichment log contains a message containing all of "origin=new status=pdf repo_found_in=pdf repo_urls=https://code.example.com/user/repo" and "url=https://arxiv.example.com/abs/0000.00001v1"

  Scenario: PDF enrichment emits status=pdf with empty repo_found_in when no code URL is found
    Given an article that has not been enriched
    And the PDF for the article has no code URLs
    When PDF enrichment is attempted with log capture
    Then the enrichment log contains a message containing all of "origin=new status=pdf repo_found_in= repo_urls= repo_context=" and "url=https://arxiv.example.com/abs/0000.00001v1"

  Scenario: PDF enrichment emits status=pdf_error when PDF bytes are invalid
    Given an article that has not been enriched
    And the PDF bytes for the article are invalid
    When PDF enrichment is attempted with log capture
    Then the enrichment log contains a message containing all of "origin=new status=pdf_error" and "url=https://arxiv.example.com/abs/0000.00001v1"

  Scenario: PDF enrichment emits semicolon-joined repo_urls when two URLs are found on different pages
    Given the accepted repo domains include "code.example.com"
    And an article that has not been enriched
    And a PDF whose page 1 contains the text "https://code.example.com/user/repo1"
    And the PDF page 2 contains the text "https://code.example.com/user/repo2"
    And the enrichment PDF is built from the page specifications
    When PDF enrichment is attempted with log capture
    Then the enrichment log contains a message containing all of "status=pdf repo_found_in=pdf" and "repo_urls=https://code.example.com/user/repo1;https://code.example.com/user/repo2"

  Scenario: PDF enrichment emits non-empty repo_context when URL has surrounding text
    Given the accepted repo domains include "code.example.com"
    And an article that has not been enriched
    And a PDF whose page 1 contains the text "find our code at https://code.example.com/user/repo"
    And the enrichment PDF is built from the page specifications
    When PDF enrichment is attempted with log capture
    Then the enrichment log contains a message containing all substrings:
      | status=pdf repo_found_in=pdf                  |
      | repo_context="p1: find our code at            |

  Scenario: PDF enrichment emits semicolon-joined repo_context when two URLs on different pages each have surrounding text
    Given the accepted repo domains include "code.example.com"
    And an article that has not been enriched
    And a PDF whose page 1 contains the text "find our code at https://code.example.com/user/repo1"
    And the PDF page 2 contains the text "see demo at https://code.example.com/user/repo2"
    And the enrichment PDF is built from the page specifications
    When PDF enrichment is attempted with log capture
    Then the enrichment log contains a message containing all substrings:
      | status=pdf repo_found_in=pdf                                                        |
      | repo_urls=https://code.example.com/user/repo1;https://code.example.com/user/repo2  |
      | repo_context="p1: find our code at                                                  |
      | p2: see demo at                                                                     |
