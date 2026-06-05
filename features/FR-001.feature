@status-todo
Feature: FR-001 Fetch articles from the arxiv API using a rolling window

  The pipeline fetches every article submitted to the configured arxiv category
  during the rolling window [today - ARXIV_MAX_BACKFILL_DAYS, today].
  It pages the arxiv API in steps of ARXIV_MAX_RESULTS results (default 50)
  and uses the configured category id.

  The rolling window replaces the former ISO week bounds to recover articles
  submitted after Thursday 14:00 ET, which the arXiv announcement schedule
  delays until after the ISO week boundary.

  The scenarios run against a local fixture HTTP server (not export.arxiv.org).
  The pipeline points at the fixture via the ARXIV_API_BASE_URL environment
  variable, which defaults to "https://export.arxiv.org" in production.
  The "today" date is injected via the PIPELINE_TODAY environment variable,
  which defaults to the current UTC date in production.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And by default the fixture server returns entries that all have a comment URL
    And no "docs/arxiv/cs.ai/atom.xml" file exists in a fresh temporary directory

  Scenario: The first API request uses rolling window bounds [today - 8, today] by default
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    When the pipeline runs to completion
    Then the fixture server received at least one request with path "/api/query"
    And the first request query string contains "search_query=cat:cs.AI+AND+submittedDate:[202605060000+TO+202605142359]"
    And the first request query string contains "start=0"
    And the first request query string contains "max_results=50"

  Scenario Outline: Rolling window date range covers [today - ARXIV_MAX_BACKFILL_DAYS, today]
    Given the environment variable PIPELINE_TODAY is "<today>"
    And the environment variable ARXIV_MAX_BACKFILL_DAYS is "<n>"
    When the pipeline runs to completion
    Then the first request query string contains "submittedDate:[<start>0000+TO+<end>2359]"

    Examples:
      | today      | n  | start    | end      |
      | 2026-05-14 | 8  | 20260506 | 20260514 |
      | 2026-05-14 | 1  | 20260513 | 20260514 |
      | 2026-05-14 | 15 | 20260429 | 20260514 |
      | 2026-05-12 | 8  | 20260504 | 20260512 |
      | 2026-12-31 | 8  | 20261223 | 20261231 |
      | 2027-01-05 | 8  | 20261228 | 20270105 |

  Scenario: The first API request sorts by submission date descending
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    When the pipeline runs to completion
    Then the first request query string contains "sortBy=submittedDate"
    And the first request query string contains "sortOrder=descending"

  Scenario: Pagination stops when a page returns fewer than ARXIV_MAX_RESULTS entries
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server returns 30 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then the fixture server received exactly 1 request

  Scenario: Pagination continues when a page returns exactly ARXIV_MAX_RESULTS entries
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server returns 50 entries for query parameter "start=0"
    And the fixture server returns 30 entries for query parameter "start=50"
    When the pipeline runs to completion
    Then the fixture server received exactly 2 requests
    And the second request query string contains "start=50"

  Scenario: A 200 response with zero entries on the first page exits zero and no atom.xml is written
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server responds with HTTP 200 and 0 entries to the first request
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: A 200 response with zero entries on a pagination page is treated as end-of-results and the pipeline succeeds
    Given the environment variable PIPELINE_TODAY is "2026-05-14"
    And the fixture server returns 50 entries for query parameter "start=0"
    And the fixture server returns 0 entries for query parameter "start=50"
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And the fixture server received exactly 2 requests
