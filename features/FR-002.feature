@status-todo
Feature: FR-002 Article inclusion filter

  An article is included in the feed if and only if both conditions hold:
  (1) the primary-category condition controlled by ARXIV_CATEGORY_STRICT,
  (2) its arxiv:comment field contains at least one "https://" URL.

  Background:
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"

  Scenario: Non-strict mode includes a cross-listed article whose comment has a URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.CV"
    And the article comment is "Code at https://github.com/foo/bar"
    When the inclusion filter is applied to the article
    Then the article is included

  Scenario: Non-strict mode excludes an article whose comment has no https URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment is "Accepted at NeurIPS 2026"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario: Non-strict mode excludes an article that has no arxiv:comment element
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article has no arxiv:comment element
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario: Non-strict mode excludes an article whose comment contains only an http URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment is "See http://example.com/code"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario: Strict mode includes an article whose primary category matches and whose comment has a URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And an article has primary category "cs.AI"
    And the article comment is "Demo: https://example.github.io/"
    When the inclusion filter is applied to the article
    Then the article is included

  Scenario: Strict mode excludes a cross-listed article even if its comment has a URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And an article has primary category "cs.CV"
    And the article comment is "Code at https://github.com/foo/bar"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario Outline: Strict mode primary-category comparison is case-insensitive
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And the environment variable ARXIV_CATEGORY_ID is "<configured>"
    And an article has primary category "<article_primary>"
    And the article comment is "https://github.com/foo/bar"
    When the inclusion filter is applied to the article
    Then the article is <outcome>

    Examples:
      | configured | article_primary | outcome  |
      | cs.AI      | cs.ai           | included |
      | cs.ai      | CS.AI           | included |
      | cs.AI      | cs.cv           | excluded |
