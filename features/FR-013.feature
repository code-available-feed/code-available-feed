@status-done
Feature: FR-013 Diagnostic logging to stdout

  The pipeline logs the API URL queried (with date bounds), the number of
  results returned per API page, and the number of articles passing the
  filter. After generating the new atom.xml the workflow logs a diff between
  the previously committed file and the newly generated one. If no previous
  file exists the diff step is skipped.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable PIPELINE_TODAY is "2026-05-14"

  Scenario: The API URL with date bounds is logged before the first request
    Given the fixture server returns 5 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "/api/query"
    And stdout contains a line containing "submittedDate:[202605110000+TO+202605172359]"

  Scenario: A per-page result count is logged for each API page
    Given the fixture server returns 50 entries for query parameter "start=0"
    And the fixture server returns 30 entries for query parameter "start=50"
    When the pipeline runs to completion
    Then stdout contains a line containing "Fetched 50 results (start=0)"
    And stdout contains a line containing "Fetched 30 results (start=50)"

  Scenario: The number of articles passing the inclusion filter is logged
    Given the fixture server returns 10 entries where 3 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line containing "3 articles passed the filter"

  Scenario: A unified diff between previous and new atom.xml is logged when a previous file exists
    Given an existing file "docs/arxiv/cs.ai/atom.xml" with known previous content
    And the fixture server returns 5 entries where all 5 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line starting with "--- "
    And stdout contains a line starting with "+++ "

  Scenario: The diff step is skipped when no previous atom.xml file exists
    Given no file "docs/arxiv/cs.ai/atom.xml" exists in a fresh temporary directory
    And the fixture server returns 5 entries where all 5 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout does not contain any line starting with "--- "
    And stdout does not contain any line starting with "+++ "
