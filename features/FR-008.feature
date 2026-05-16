@status-done
Feature: FR-008 Repository variable resolution

  Two repository variables control filtering: ARXIV_CATEGORY_ID (default
  "cs.AI") and ARXIV_CATEGORY_STRICT (default "false"). The strict-mode value
  parsing is case-insensitive: only the value "true" (any casing) enables
  strict mode; any other value, including empty string or unset variable,
  disables it.

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
