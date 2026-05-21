@status-done
Feature: FR-008 Repository variable resolution

  Two repository variables control filtering: ARXIV_CATEGORY_ID (default
  "cs.AI") and ARXIV_CATEGORY_STRICT (default "false"). Two additional
  variables control error handling and staleness alerting:
  ARXIV_CONTINUE_ON_API_ERROR (default "false") and ARXIV_MAX_STALENESS_DAYS
  (default "-1"). All boolean-like variables follow the same convention: only
  the case-insensitive literal "true" enables the mode; any other value
  including empty string or unset disables it.

  Scenario: ARXIV_CATEGORY_ID defaults to "cs.AI" when the environment variable is unset
    Given the environment variable ARXIV_CATEGORY_ID is unset
    When the configuration is resolved
    Then the resolved category id is "cs.AI"

  Scenario: ARXIV_CATEGORY_ID passes the configured value through when set
    Given the environment variable ARXIV_CATEGORY_ID is "cs.CV"
    When the configuration is resolved
    Then the resolved category id is "cs.CV"

  Scenario Outline: ARXIV_CATEGORY_STRICT enables strict mode only for the case-insensitive literal "true"
    Given the environment variable ARXIV_CATEGORY_STRICT is "<value>"
    When the configuration is resolved
    Then the resolved strict-mode flag is <expected>

    Examples:
      | value | expected |
      | true  | true     |
      | True  | true     |
      | TRUE  | true     |
      | false | false    |
      | False | false    |
      |       | false    |
      | yes   | false    |
      | 1     | false    |
      | on    | false    |

  Scenario: ARXIV_CATEGORY_STRICT defaults to false when the environment variable is unset
    Given the environment variable ARXIV_CATEGORY_STRICT is unset
    When the configuration is resolved
    Then the resolved strict-mode flag is false

  Scenario: ARXIV_CATEGORY_ID with an invalid format raises ValueError
    Given the environment variable ARXIV_CATEGORY_ID is "../etc/passwd"
    When the configuration category id is resolved
    Then resolve_category_id raises ValueError

  Scenario Outline: ARXIV_CONTINUE_ON_API_ERROR enables continue mode only for the case-insensitive literal "true"
    Given the environment variable ARXIV_CONTINUE_ON_API_ERROR is "<value>"
    When the continue-on-api-error flag is resolved
    Then the resolved continue-on-api-error flag is <expected>

    Examples:
      | value | expected |
      | true  | true     |
      | True  | true     |
      | TRUE  | true     |
      | false | false    |
      | False | false    |
      |       | false    |
      | yes   | false    |
      | 1     | false    |
      | on    | false    |

  Scenario: ARXIV_CONTINUE_ON_API_ERROR defaults to false when the environment variable is unset
    Given the environment variable ARXIV_CONTINUE_ON_API_ERROR is unset
    When the continue-on-api-error flag is resolved
    Then the resolved continue-on-api-error flag is false

  Scenario Outline: ARXIV_MAX_STALENESS_DAYS accepts -1 (disabled) and positive integers
    Given the environment variable ARXIV_MAX_STALENESS_DAYS is "<value>"
    When the staleness days configuration is resolved
    Then ARXIV_MAX_STALENESS_DAYS is accepted

    Examples:
      | value |
      | -1    |
      | 1     |
      | 5     |

  Scenario Outline: ARXIV_MAX_STALENESS_DAYS rejects zero, negatives other than -1, and non-integers
    Given the environment variable ARXIV_MAX_STALENESS_DAYS is "<value>"
    When the staleness days configuration is resolved
    Then ARXIV_MAX_STALENESS_DAYS is rejected with ValueError

    Examples:
      | value      |
      | 0          |
      | -2         |
      | notanumber |
      | 1.5        |
