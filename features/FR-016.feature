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
