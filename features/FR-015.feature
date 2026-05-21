@status-done
Feature: FR-015 Graceful API error continuation and feed staleness alert

  ARXIV_CONTINUE_ON_API_ERROR (default false): when set to the
  case-insensitive literal "true", the pipeline exits 0 on API failure
  instead of 1; any other value including unset preserves the default
  exit-1 behaviour. ARXIV_MAX_STALENESS_DAYS (default -1, disabled) causes
  check_feed_staleness to exit non-zero when the feed is older than the
  configured threshold in whole calendar days.

  Scenario: ARXIV_CONTINUE_ON_API_ERROR=true exits zero when all first-page retries are exhausted
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And the environment variable ARXIV_CONTINUE_ON_API_ERROR is "true"
    And the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 503 to every request
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: ARXIV_CONTINUE_ON_API_ERROR=true exits zero when a pagination request fails
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And the environment variable ARXIV_CONTINUE_ON_API_ERROR is "true"
    And the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 200 and 50 entries to the first request
    And the fixture server responds with HTTP 503 to the second request
    When the pipeline runs to completion
    Then the pipeline exit code is 0
    And no file "docs/arxiv/cs.ai/atom.xml" was written by this run

  Scenario: ARXIV_CONTINUE_ON_API_ERROR unset exits non-zero when all retries are exhausted
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And the environment variable ARXIV_CONTINUE_ON_API_ERROR is unset
    And the environment variable RETRY_BACKOFF_BASE_SECONDS is "0.1"
    And the fixture server responds with HTTP 503 to every request
    When the pipeline runs to completion
    Then the pipeline exit code is non-zero

  Scenario: ARXIV_MAX_STALENESS_DAYS=-1 skips the staleness check regardless of feed age
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And a minimal feed file "docs/arxiv/cs.ai/atom.xml" with newest entry published "2026-01-01T00:00:00Z"
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "-1"
    When the staleness check runs
    Then the staleness check exits with code 0

  Scenario: Feed within the staleness threshold passes the check
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And a minimal feed file "docs/arxiv/cs.ai/atom.xml" with newest entry published "2026-05-11T00:00:00Z"
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "5"
    When the staleness check runs
    Then the staleness check exits with code 0

  Scenario: Feed exactly at the staleness threshold passes the check
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And a minimal feed file "docs/arxiv/cs.ai/atom.xml" with newest entry published "2026-05-09T00:00:00Z"
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "5"
    When the staleness check runs
    Then the staleness check exits with code 0

  Scenario: Feed one day beyond the staleness threshold fails the check
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And a minimal feed file "docs/arxiv/cs.ai/atom.xml" with newest entry published "2026-05-08T00:00:00Z"
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "5"
    When the staleness check runs
    Then the staleness check exits with non-zero code

  Scenario: Missing feed file passes the staleness check on first run
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And no "docs/arxiv/cs.ai/atom.xml" file exists in a fresh temporary directory
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "5"
    When the staleness check runs
    Then the staleness check exits with code 0

  Scenario: ARXIV_MAX_STALENESS_DAYS=0 is rejected as invalid
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And a minimal feed file "docs/arxiv/cs.ai/atom.xml" with newest entry published "2026-05-14T00:00:00Z"
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "0"
    When the staleness check runs
    Then the staleness check exits with non-zero code

  Scenario: Non-integer ARXIV_MAX_STALENESS_DAYS is rejected as invalid
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And a minimal feed file "docs/arxiv/cs.ai/atom.xml" with newest entry published "2026-05-14T00:00:00Z"
    And the environment variable ARXIV_MAX_STALENESS_DAYS is "notanumber"
    When the staleness check runs
    Then the staleness check exits with non-zero code
