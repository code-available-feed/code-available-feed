@status-done
Feature: FR-002 Article inclusion filter with cascading code-URL search

  An article is included in the feed if and only if both conditions hold:
  (1) belongs to the configured category (behavior controlled by
  ARXIV_CATEGORY_STRICT), and (2) a code-availability URL was found by the
  cascading search across three sources, stopping at the first match:
  comment (any https:// URL), abstract (accepted-domain URLs only), or
  PDF body (accepted-domain URLs only, tested in FR-016).

  The accepted domain set is a module-level constant in production
  (github.com, gitlab.com, huggingface.co, *.github.io) but is injectable
  in tests via a parameter so scenarios use example.com subdomains.
  Comment URLs accept any https:// URL (not restricted to accepted domains)
  because the comment field is a deliberate, structured annotation.

  Background:
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"

  # --- Existing comment-URL scenarios (unchanged behavior) ---

  Scenario: Non-strict mode includes a cross-listed article whose comment has a URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.CV"
    And the article comment is "Code at https://code.example.com/foo/bar"
    When the inclusion filter is applied to the article
    Then the article is included

  Scenario: Non-strict mode excludes an article whose comment has no https URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment is "Accepted at NeurIPS 2026"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario Outline: Non-strict mode excludes an article whose arxiv:comment element is absent or empty
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment element is "<element_state>"
    When the inclusion filter is applied to the article
    Then the article is excluded

    Examples:
      | element_state |
      | absent        |
      | empty         |

  Scenario: Non-strict mode excludes an article whose comment contains only an http URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment is "See http://example.com/code"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario: Strict mode includes an article whose primary category matches and whose comment has a URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And an article has primary category "cs.AI"
    And the article comment is "Demo: https://demo.example.com/"
    When the inclusion filter is applied to the article
    Then the article is included

  Scenario: Strict mode excludes a cross-listed article even if its comment has a URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And an article has primary category "cs.CV"
    And the article comment is "Code at https://code.example.com/foo/bar"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario Outline: Strict mode primary-category comparison is case-insensitive
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And the environment variable ARXIV_CATEGORY_ID is "<configured>"
    And an article has primary category "<article_primary>"
    And the article comment is "https://code.example.com/foo/bar"
    When the inclusion filter is applied to the article
    Then the article is <outcome>

    Examples:
      | configured | article_primary | outcome  |
      | cs.AI      | cs.ai           | included |
      | cs.ai      | CS.AI           | included |
      | cS.Ai      | CS.AI           | included |
      | cs.AI      | cs.cv           | excluded |

  Scenario: A comment containing only a degenerate URL with no path is excluded
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment is "See https://."
    When the inclusion filter is applied to the article
    Then the article is excluded

  # --- Abstract URL cascade scenarios ---

  Scenario: Article with accepted-domain URL in abstract and no comment URL is included via abstract
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code at https://code.example.com/user/repo"
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "abstract"

  Scenario: Article with non-accepted-domain URL in abstract only is excluded
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "See https://journal.example.org/paper"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario Outline: Each accepted domain in abstract triggers inclusion
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "<domain>"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code: https://<domain>/user/repo"
    When the inclusion filter is applied to the article
    Then the article is included

    Examples:
      | domain              |
      | code.example.com    |
      | forge.example.com   |
      | hub.example.com     |

  Scenario: Wildcard domain suffix in abstract triggers inclusion
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domain suffixes include ".pages.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Project: https://user.pages.example.com/project"
    When the inclusion filter is applied to the article
    Then the article is included

  Scenario: Comment URL takes priority over abstract URL in the cascade
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment is "Code at https://mysite.example.com/repo"
    And the article abstract is "Also at https://code.example.com/user/repo"
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "comment"

  Scenario: Bare domain URL without https scheme in abstract is extracted
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code: code.example.com/user/repo"
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "abstract"

  Scenario: Article with no comment and no accepted-domain URL in abstract is excluded
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "We present a novel approach to machine learning."
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario: Strict mode excludes a cross-listed article even with accepted-domain URL in abstract
    Given the environment variable ARXIV_CATEGORY_STRICT is "true"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.CV"
    And the article comment element is "absent"
    And the article abstract is "Code at https://code.example.com/user/repo"
    When the inclusion filter is applied to the article
    Then the article is excluded

  Scenario: Comment with any-domain URL takes priority over abstract with accepted-domain URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment is "Project: https://mysite.example.org/demo"
    And the article abstract is "Code at https://code.example.com/user/repo"
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "comment"
