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

  # --- Malformed abstract URL scenarios (reproduce a production crash and a ---
  # --- data-corruption defect in _extract_candidate_urls; expected to fail ---
  # --- until the extraction fix lands) ---

  Scenario: Markdown-style duplicate URL against an accepted domain suffix does not crash the filter
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domain suffixes include ".pages.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Project page: [https://user.pages.example.com/project](https://user.pages.example.com/project)."
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "abstract"
    And the article repo_urls is "https://user.pages.example.com/project"

  Scenario: Markdown-style duplicate URL against an accepted exact domain yields the clean URL
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code: [https://code.example.com/user/repo](https://code.example.com/user/repo)."
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "abstract"
    And the article repo_urls is "https://code.example.com/user/repo"

  Scenario: Two independent markdown-style duplicate URLs in the same abstract are both extracted cleanly
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And the accepted repo domains include "forge.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code: [https://code.example.com/a](https://code.example.com/a). Mirror: [https://forge.example.com/b](https://forge.example.com/b)."
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "abstract"
    And the article repo_urls is "https://code.example.com/a;https://forge.example.com/b"

  # --- Malformed candidate URL diagnostic logging (FR-013 log format) ---
  #
  # This uses a URL that is unparseable on its own terms (an unbalanced "["
  # right after the scheme, which urlparse rejects as an invalid IPv6 host),
  # deliberately independent of the markdown-duplicate-URL scenarios above:
  # once those are fixed to extract a clean candidate, they must stop
  # producing any malformed candidate at all, so they cannot serve as a
  # stable regression test for this logging behavior.

  Scenario: A candidate URL that fails to parse is logged as malformed and excluded, not crashed
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code available at https://[bad-ipv6/repo for testing."
    When the inclusion filter is applied to the article with log capture
    Then the inclusion filter log contains a message containing "status=abstract_malformed_url"
    And the article is excluded

  # --- Regression: a URL that legitimately embeds another URL as a query ---
  # --- parameter must be captured whole, not truncated at the embedded ---
  # --- "https://".  This is the case the markdown-duplicate-URL fix above ---
  # --- must not break: unlike "[url](url)", there is no "[...](...)" ---
  # --- framing here, so _MARKDOWN_DUPLICATE_URL_PATTERN must not match it. ---

  Scenario: A URL containing another URL as a query parameter is captured whole, not truncated
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And the accepted repo domains include "code.example.com"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "See https://code.example.com/redirect?url=https://other.example.com/page for details."
    When the inclusion filter is applied to the article
    Then the article is included
    And the article repo_found_in is "abstract"
    And the article repo_urls is "https://code.example.com/redirect?url=https://other.example.com/page"

  # --- Diagnostic logging for valid URLs on domains outside the accepted ---
  # --- list, to spot repository providers worth adding to ACCEPTED_REPO_DOMAINS ---
  # --- / ACCEPTED_REPO_DOMAIN_SUFFIXES.  The second scenario is a single, ---
  # --- deliberate exception to the "never use real domain names in tests" ---
  # --- rule: it exercises the real production ACCEPTED_REPO_DOMAINS default ---
  # --- (no domain override step), so it must use an actually-accepted real ---
  # --- domain rather than an injected fictitious one. ---

  Scenario: A syntactically valid URL on a domain outside the accepted list is logged for review
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code at https://code.example.com/user/repo for the curious."
    When the inclusion filter is applied to the article with log capture
    Then the inclusion filter log contains a message containing "status=abstract_rejected_domain_url"
    And the inclusion filter log contains a message containing "hostname=code.example.com"
    And the article is excluded

  Scenario: A URL on a genuinely accepted domain does not trigger the rejected-domain log line
    Given the environment variable ARXIV_CATEGORY_STRICT is "false"
    And an article has primary category "cs.AI"
    And the article comment element is "absent"
    And the article abstract is "Code at https://github.com/example-user/example-repo for the curious."
    When the inclusion filter is applied to the article with log capture
    Then the inclusion filter log does not contain a message containing "status=abstract_rejected_domain_url"
    And the article is included
    And the article repo_found_in is "abstract"
