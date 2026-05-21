@status-done
Feature: FR-009 Feed self-URL construction

  The feed <id> and <link rel="self" href="..."/> are set to the canonical
  GitHub Pages URL of the feed, derived from GITHUB_REPOSITORY (always set by
  GitHub Actions in the form "owner/repo") and the lowercased category id.

  Scenario Outline: Feed URL is constructed from GITHUB_REPOSITORY and the lowercased category id
    Given the environment variable GITHUB_REPOSITORY is "<repository>"
    And the environment variable ARXIV_CATEGORY_ID is "<category>"
    When the feed self-URL is constructed
    Then the feed self-URL is "<expected_url>"

    Examples:
      | repository                | category | expected_url                                                     |
      | owner/code-available-feed | cs.AI    | https://owner.github.io/code-available-feed/arxiv/cs.ai/atom.xml |
      | owner/code-available-feed | cs.ai    | https://owner.github.io/code-available-feed/arxiv/cs.ai/atom.xml |
      | exampleuser/my-fork       | cs.CV    | https://exampleuser.github.io/my-fork/arxiv/cs.cv/atom.xml       |

  Scenario: Feed self-URL appears as both <feed><id> and <feed><link rel="self" href="..."/>
    Given the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And one input article with any valid fields
    When the feed is generated
    Then the feed-level id element value is "https://owner.github.io/code-available-feed/arxiv/cs.ai/atom.xml"
    And the feed-level link element with rel "self" has href "https://owner.github.io/code-available-feed/arxiv/cs.ai/atom.xml"

  Scenario: Entry id is the versioned arxiv abstract page URL, not the feed self-URL
    Given the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And one input article whose abstract page URL is "https://arxiv.org/abs/0000.00001v1"
    When the feed is generated
    Then the entry id element value is "https://arxiv.org/abs/0000.00001v1"
