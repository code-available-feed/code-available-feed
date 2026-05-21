@status-done
Feature: FR-014 Feed alternate link to the source GitHub repository

  The generated Atom feed includes a feed-level
  <link rel="alternate" href="https://github.com/{owner}/{repo}"/> element
  derived from GITHUB_REPOSITORY, giving feed readers a direct link to the
  pipeline source repository.

  Scenario Outline: GitHub repo URL is constructed from GITHUB_REPOSITORY
    Given the environment variable GITHUB_REPOSITORY is "<repository>"
    When the GitHub repo URL is constructed
    Then the GitHub repo URL is "<expected_url>"

    Examples:
      | repository                | expected_url                                 |
      | owner/code-available-feed | https://github.com/owner/code-available-feed |
      | exampleuser/my-fork       | https://github.com/exampleuser/my-fork       |

  Scenario: Feed alternate link points to the GitHub repository
    Given the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And one input article with any valid fields
    When the feed is generated
    Then the feed-level link element with rel "alternate" has href "https://github.com/owner/code-available-feed"
