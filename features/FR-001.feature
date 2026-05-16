@status-done
Feature: FR-001 Fetch the current ISO week from the arxiv API

  The pipeline fetches every article submitted to the configured arxiv category
  during the current ISO calendar week (Monday 00:00 UTC to Sunday 23:59 UTC).
  It pages the arxiv API in steps of 2000 results and uses the configured
  category id.

  The scenarios run against a local fixture HTTP server (not export.arxiv.org).
  The pipeline points at the fixture via the ARXIV_API_BASE_URL environment
  variable, which defaults to "https://export.arxiv.org" in production.
  The "today" date is injected via the PIPELINE_TODAY environment variable,
  which defaults to the current UTC date in production.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "marcindulak/code-available-feed"
    And by default the fixture server returns entries that all have a comment URL
    And no "docs/arxiv/cs.ai/atom.xml" file exists in a fresh temporary directory

  Scenario: The first API request uses the current ISO week date bounds
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    When the pipeline runs to completion
    Then the fixture server received at least one request with path "/api/query"
    And the first request query string contains "search_query=cat:cs.AI+AND+submittedDate:[202605110000+TO+202605172359]"
    And the first request query string contains "start=0"
    And the first request query string contains "max_results=2000"

  Scenario Outline: Date range covers the full current ISO week regardless of which weekday "today" is
    Given the environment variable PIPELINE_TODAY is "<today>"
    When the pipeline runs to completion
    Then the first request query string contains "submittedDate:[<monday>0000+TO+<sunday>2359]"

    Examples:
      | today      | monday   | sunday   |
      | 2026-05-11 | 20260511 | 20260517 |
      | 2026-05-14 | 20260511 | 20260517 |
      | 2026-05-17 | 20260511 | 20260517 |
      | 2026-12-31 | 20261228 | 20270103 |
      | 2027-01-01 | 20261228 | 20270103 |

  Scenario: The first API request sorts by submission date descending
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    When the pipeline runs to completion
    Then the first request query string contains "sortBy=submittedDate"
    And the first request query string contains "sortOrder=descending"

  Scenario: Pagination stops when a page returns fewer than 2000 entries
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server returns 1000 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then the fixture server received exactly 1 request

  Scenario: Pagination continues when a page returns exactly 2000 entries
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server returns 2000 entries for query parameter "start=0"
    And the fixture server returns 350 entries for query parameter "start=2000"
    When the pipeline runs to completion
    Then the fixture server received exactly 2 requests
    And the second request query string contains "start=2000"

  Scenario: A 200 response with zero entries on the first page exits non-zero and no atom.xml is written
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server responds with HTTP 200 and 0 entries to the first request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: A 200 response with zero entries on a pagination page is treated as end-of-results and the pipeline succeeds
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server returns 2000 entries for query parameter "start=0"
    And the fixture server returns 0 entries for query parameter "start=2000"
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And the fixture server received exactly 2 requests
