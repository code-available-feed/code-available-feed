@status-todo
Feature: FR-011 Retry on API failure and fail-loud on zero-result responses

  If the arxiv API returns a non-200 HTTP status the pipeline retries the
  request up to 2 times with exponential backoff (10 seconds after the first
  failure, 20 seconds after the second failure). If all retries fail the
  pipeline exits non-zero and no commit is made. If the API returns 200 but
  zero entries for a date range that should contain entries the pipeline also
  exits non-zero and no commit is made.

  The base backoff duration is read from the environment variable
  RETRY_BACKOFF_BASE_SECONDS, which defaults to "10" in production. Tests set
  this variable to "0" to avoid wall-clock waits in fast scenarios, and to
  the production value in a single dedicated scenario that exercises the
  default timing.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"

  Scenario: One transient 503 followed by a successful 200 succeeds after one retry
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the fixture server responds with HTTP 503 to the first request
    And the fixture server responds with HTTP 200 and 5 entries to subsequent requests
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And the fixture server received exactly 2 requests
    And the generated atom.xml contains 5 entries

  Scenario: Two transient 503s followed by a successful 200 succeeds after two retries
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the fixture server responds with HTTP 503 to the first 2 requests
    And the fixture server responds with HTTP 200 and 3 entries to subsequent requests
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And the fixture server received exactly 3 requests

  Scenario: Three consecutive 503s exit non-zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the fixture server responds with HTTP 503 to every request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: A 200 response with zero entries exits non-zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the fixture server responds with HTTP 200 and 0 entries to the first request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: Default backoff base produces a 10-second wait between the first and second attempt
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is unset
    And the fixture server responds with HTTP 503 to the first request
    And the fixture server responds with HTTP 200 and 1 entry to the second request
    When the pipeline runs to completion
    Then the gap between the first and second request received by the fixture server is at least 10 seconds
    And the pipeline exit code is 0
