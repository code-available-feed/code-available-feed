@status-done
Feature: FR-011 Retry on API failure

  If the first arxiv API request (start=0) returns a non-200 HTTP status the
  pipeline retries it with exponential backoff (N × RETRY_BACKOFF_BASE_SECONDS
  seconds before the N-th retry). If all retries are exhausted the pipeline
  exits non-zero and no commit is made. A non-200 response on any subsequent
  pagination request (start>0) causes the pipeline to exit immediately without
  retrying.

  The base backoff duration is read from the environment variable
  RETRY_BACKOFF_BASE_SECONDS. All scenarios set this variable to "0.1" so the
  sleep code path is exercised with a small positive value without adding
  meaningful wall-clock wait. The correctness of the default value and retry
  count are verified by code review.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable PIPELINE_TODAY is "2026-05-14"

  Scenario: One transient 503 followed by a successful 200 succeeds after one retry
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 503 to the first request
    And the fixture server responds with HTTP 200 and 5 entries to subsequent requests
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And the fixture server received exactly 2 requests
    And the generated atom.xml contains 5 entries

  Scenario: Two transient 503s followed by a successful 200 succeeds after two retries
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 503 to the first 2 requests
    And the fixture server responds with HTTP 200 and 3 entries to subsequent requests
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And the fixture server received exactly 3 requests

  Scenario: A non-200 response on a pagination page exits non-zero immediately without retrying
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 200 and 50 entries to the first request
    And the fixture server responds with HTTP 503 to the second request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: All retries exhausted by consecutive 503s exit non-zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 503 to every request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run
    And the fixture server received exactly 4 requests

  Scenario: Zero articles after inclusion filtering exits zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the environment variable ARXIV_CATEGORY_STRICT is "true"
    And the fixture server responds with HTTP 200 and 5 entries to the first request
    And all 5 entries have primary category "cs.CV" and a comment URL
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: Unset GITHUB_REPOSITORY exits non-zero and no atom.xml is written
    Given the environment variable GITHUB_REPOSITORY is unset
    And the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: HTTP 200 with malformed XML body exits non-zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 200 and a malformed XML body to the first request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

