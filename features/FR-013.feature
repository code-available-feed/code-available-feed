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
    And the environment variable ARXIV_MAX_BACKFILL_DAYS is "8"

  Scenario: The API URL with date bounds is logged before the first request
    Given the fixture server returns 5 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "/api/query"
    And stdout contains a line containing "submittedDate:[202605060000+TO+202605142359]"

  Scenario: A per-page result count is logged for each API page
    Given the fixture server returns 50 entries for query parameter "start=0"
    And the fixture server returns 30 entries for query parameter "start=50"
    When the pipeline runs to completion
    Then stdout contains a line containing "fetched 50 results (start=0)"
    And stdout contains a line containing "fetched 30 results (start=50)"

  Scenario: The number of articles passing the inclusion filter is logged
    Given the fixture server returns 10 entries where 3 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line containing "3 articles (0 aged out of the window, 3 new) passed the filter"

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

  Scenario: At least one stdout line is valid JSON with the required log keys
    Given the fixture server returns 5 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then at least one stdout line parses as JSON with keys "asctime", "levelname", "name", "funcName", "message"

  # --- Cache restoration and enrichment logging scenarios ---
  # These scenarios assert the structured per-article log format described in debug-log-problem.md.

  Scenario: A previously-passed article restored from cache is logged with its source
    Given the prior atom.xml contains processed entries:
      | url                                     | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1  | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 1 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a log message containing all of "status=cached repo_found_in=comment" and "url=https://arxiv.org/abs/fixture.000001v1"

  Scenario: A previously-failed article restored from cache is logged with empty repo_found_in
    Given the prior atom.xml contains processed entries:
      | url                                     | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1  |               | 2026-05-12T10:00:00Z |
      | https://arxiv.org/abs/fixture.000002v1  | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 2 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a log message containing all of "status=cached repo_found_in= " and "url=https://arxiv.org/abs/fixture.000001v1"

  Scenario: A new article whose comment contains no URL logs status=comment with empty repo_found_in
    Given the fixture server returns 1 entries without any URLs for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a log message containing "status=comment repo_found_in= "

  Scenario: A new article with a comment URL logs status=comment with repo_found_in=comment
    Given the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a log message containing "status=comment repo_found_in=comment"

  Scenario: A new article with an abstract URL and no comment logs status=abstract found and status=comment not found
    Given the fixture server returns 1 entries with abstract URLs for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a log message containing "status=comment repo_found_in= "
    And stdout contains a log message containing "status=abstract repo_found_in=abstract"

  Scenario: A new article with no comment and no abstract URL logs both stages as not found
    Given the fixture server returns 1 entries without any URLs for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a log message containing "status=comment repo_found_in= "
    And stdout contains a log message containing "status=abstract repo_found_in= "

  Scenario: An article in the cache within the date window but absent from the API is logged as aged out
    Given the prior atom.xml contains processed entries:
      | url                                      | repo_found_in | updated              |
      | https://arxiv.org/abs/prior.000001v1     | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 1 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a log message containing all of "status=aged_out" and "url=https://arxiv.org/abs/prior.000001v1"

  Scenario: An article with published before the window and updated within it shows published in the aged-out log
    Given the prior atom.xml contains processed entries:
      | url                                      | repo_found_in | published            | updated              |
      | https://arxiv.org/abs/prior.000001v1     | comment       | 2026-04-01T00:00:00Z | 2026-05-10T00:00:00Z |
    And the fixture server returns 1 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "0 aged out of the window, 1 new to enrich"
    And stdout contains a log message containing all of "status=aged_out" and "published=2026-04-01T00:00:00Z updated=2026-05-10T00:00:00Z"
    And stdout contains a line containing "1 aged out of the window"

  Scenario: A new article that passes the filter logs status=included with origin=new
    Given the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a log message containing all of "origin=new status=included repo_found_in=comment" and "url=https://arxiv.org/abs/fixture.000001v1"

  Scenario: A previously-cached passing article logs status=included with origin=cache
    Given the prior atom.xml contains processed entries:
      | url                                    | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1 | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a log message containing all of "origin=cache status=included repo_found_in=comment" and "url=https://arxiv.org/abs/fixture.000001v1"

  Scenario: A previously-cached failing article logs status=rejected with origin=cache
    Given the prior atom.xml contains processed entries:
      | url                                    | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1 |               | 2026-05-12T10:00:00Z |
    And the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a log message containing all of "origin=cache status=rejected repo_found_in= repo_urls=" and "url=https://arxiv.org/abs/fixture.000001v1"

  Scenario: Filter summary aged-out count reflects articles absent from the API
    Given the prior atom.xml contains processed entries:
      | url                                      | repo_found_in | updated              |
      | https://arxiv.org/abs/prior.000001v1     | comment       | 2026-05-12T10:00:00Z |
      | https://arxiv.org/abs/prior.000002v1     | comment       | 2026-05-12T10:00:00Z |
      | https://arxiv.org/abs/prior.000003v1     | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 1 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains 3 log messages containing "status=aged_out"
    And stdout contains a line containing "3 aged out of the window"

  # --- Exhaustive fetch-summary combinations ---
  # The fetch-summary line is:
  #   N articles fetched from the API, K articles loaded from cache,
  #   M aged out of the window, J new to enrich
  # where N = K + J (constraint) and M is independent (prior entries outside date window).

  Scenario: Fetch summary shows all new on first run when there is no prior processed dict
    Given the fixture server returns 2 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "0 articles loaded from cache, 0 aged out of the window, 2 new to enrich"

  Scenario: Fetch summary shows all cached when every API article is in the processed dict
    Given the prior atom.xml contains processed entries:
      | url                                    | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1 | comment       | 2026-05-12T10:00:00Z |
      | https://arxiv.org/abs/fixture.000002v1 | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 2 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "2 articles loaded from cache, 0 aged out of the window, 0 new to enrich"

  Scenario: Fetch summary shows partial cache when only some API articles are in the processed dict
    Given the prior atom.xml contains processed entries:
      | url                                    | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1 | comment       | 2026-05-12T10:00:00Z |
    And the fixture server returns 2 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "1 articles loaded from cache, 0 aged out of the window, 1 new to enrich"

  Scenario: Fetch summary shows date-aged-out count when prior dict has entries outside the date window
    Given the prior atom.xml contains processed entries:
      | url                                    | repo_found_in | updated              |
      | https://arxiv.org/abs/fixture.000001v1 | comment       | 2026-05-12T10:00:00Z |
      | https://arxiv.org/abs/prior.000001v1   | comment       | 2026-04-01T00:00:00Z |
    And the fixture server returns 1 entries for query parameter "start=0"
    When the pipeline runs to completion
    Then stdout contains a line containing "1 articles loaded from cache, 1 aged out of the window, 0 new to enrich"

  # --- Exhaustive filter-summary combinations ---
  # The filter-summary line is:
  #   N articles (A aged out, B new) passed the filter ...; F (Fa, Fb) articles failed the filter
  # where A = n_filtered_aged_out, B = n_filtered_new,
  #       Fa = n_failed_aged_out, Fb = n_failed_new.

  Scenario: Filter summary shows both fetch aged-out and filter aged-out when a previously-passing article expires by date
    Given the prior atom.xml contains processed entries:
      | url                                  | repo_found_in | updated              |
      | https://arxiv.org/abs/prior.000001v1 | comment       | 2026-04-01T00:00:00Z |
    And the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line containing "1 aged out of the window, 1 new to enrich"
    And stdout contains a line containing "(1 aged out of the window, 1 new) passed the filter"

  Scenario: Filter summary shows fetch aged-out but not filter aged-out when a previously-failing article expires by date
    Given the prior atom.xml contains processed entries:
      | url                                  | repo_found_in | updated              |
      | https://arxiv.org/abs/prior.000001v1 |               | 2026-04-01T00:00:00Z |
    And the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line containing "1 aged out of the window, 1 new to enrich"
    And stdout contains a line containing "(0 aged out of the window, 1 new) passed the filter"
    And stdout contains a line containing "0 (1, 0) articles failed the filter"

  Scenario: Filter summary shows failed aged-out without fetch aged-out when an in-window failing article is absent from the API
    Given the prior atom.xml contains processed entries:
      | url                                  | repo_found_in | updated              |
      | https://arxiv.org/abs/prior.000001v1 |               | 2026-05-10T00:00:00Z |
    And the fixture server returns 1 entries where all 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line containing "0 aged out of the window, 1 new to enrich"
    And stdout contains a line containing "(0 aged out of the window, 1 new) passed the filter"
    And stdout contains a line containing "0 (1, 0) articles failed the filter"

  Scenario: Filter summary shows failed new count when there are articles without code URLs
    Given the fixture server returns 2 entries where 1 satisfy the inclusion filter
    When the pipeline runs to completion
    Then stdout contains a line containing "1 (0, 1) article failed the filter"
