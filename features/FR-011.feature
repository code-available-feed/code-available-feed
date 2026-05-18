@status-todo
Feature: FR-011 Retry on API failure

  If the first arxiv API request (start=0) returns a non-200 HTTP status the
  pipeline retries it up to 2 times with exponential backoff (10 seconds after
  the first failure, 20 seconds after the second failure). If all retries fail
  the pipeline exits non-zero and no commit is made. A non-200 response on any
  subsequent pagination request (start>0) causes the pipeline to exit
  immediately without retrying.

  The base backoff duration is read from the environment variable
  RETRY_BACKOFF_BASE_SECONDS, which defaults to "30" in production. All
  scenarios set this variable to "0" to avoid wall-clock waits. The
  correctness of the 10-second default value is verified by code review.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "marcindulak/code-available-feed"
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

  Scenario: A non-200 response on a pagination page exits non-zero immediately without retrying
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the fixture server responds with HTTP 200 and 2000 entries to the first request
    And the fixture server responds with HTTP 503 to the second request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: Three consecutive 503s exit non-zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the fixture server responds with HTTP 503 to every request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: Zero articles after inclusion filtering exits zero and no atom.xml is written
    Given the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    And the environment variable ARXIV_CATEGORY_STRICT is "true"
    And the fixture server responds with HTTP 200 and 5 entries to the first request
    And all 5 entries have primary category "cs.CV" and a comment URL
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: Unset GITHUB_REPOSITORY exits non-zero and no atom.xml is written
    Given the environment variable GITHUB_REPOSITORY is unset
    And the environment variable RETRY_BACKOFF_BASE_SECONDS is "0"
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

