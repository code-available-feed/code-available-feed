@status-done
Feature: FR-004 Atom 1.0 feed generation

  The pipeline generates an Atom 1.0 feed (RFC 4287) from the collected
  articles. Articles are sorted by first arxiv publication date descending
  (newest first). The top-level feed updated value is the published date of
  the first article in that order.

  Background:
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"

  Scenario: Each entry contains the required Atom elements in the required form
    Given one input article with:
      | field                  | value                                                |
      | title                  | Entity-Consistent Video Generation                   |
      | authors                | Alice Example, Bob Sample                            |
      | primary_category       | cs.CV                                                |
      | abstract_url           | https://arxiv.org/abs/2605.15199v1                   |
      | published              | 2026-05-12T11:30:00Z                                 |
      | updated                | 2026-05-12T11:30:00Z                                 |
      | comment_urls           | https://github.com/foo/bar, https://foo.github.io/   |
    When the feed is generated
    Then the entry has title "[cs.CV] Entity-Consistent Video Generation"
    And the entry has author names "Alice Example" then "Bob Sample" in document order
    And the entry has category element with term "cs.CV" and scheme "http://arxiv.org/schemas/atom"
    And the entry has id "https://arxiv.org/abs/2605.15199v1"
    And the entry has link rel "alternate" type "text/html" with href "https://arxiv.org/abs/2605.15199v1"
    And the entry has published "2026-05-12T11:30:00Z"
    And the entry has updated "2026-05-12T11:30:00Z"
    And the entry has content type "text" with value "https://github.com/foo/bar\nhttps://foo.github.io/"

  Scenario: Title is prefixed with the primary category in brackets even when the primary category matches the configured category
    Given one input article with:
      | field            | value                                      |
      | title            | A Paper Title                              |
      | authors          | Test Author                                |
      | primary_category | cs.AI                                      |
      | abstract_url     | https://arxiv.org/abs/0001.00001v1         |
      | published        | 2026-05-12T11:30:00Z                       |
      | updated          | 2026-05-12T11:30:00Z                       |
      | comment_urls     | https://example.com/                       |
    When the feed is generated
    Then the entry has title "[cs.AI] A Paper Title"

  Scenario: Articles are sorted by published descending
    Given three input articles:
      | title   | authors      | primary_category | abstract_url                              | published            | updated              | comment_urls              |
      | Paper A | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00001v1        | 2026-05-10T08:00:00Z | 2026-05-10T08:00:00Z | https://example.com/a     |
      | Paper B | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00002v1        | 2026-05-14T15:00:00Z | 2026-05-14T15:00:00Z | https://example.com/b     |
      | Paper C | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00003v1        | 2026-05-12T09:00:00Z | 2026-05-12T09:00:00Z | https://example.com/c     |
    When the feed is generated
    Then the entry published dates in document order are "2026-05-14T15:00:00Z" then "2026-05-12T09:00:00Z" then "2026-05-10T08:00:00Z"

  Scenario: A same-week revision does not change article position and feed updated uses published not updated
    Given three input articles:
      | title   | authors      | primary_category | abstract_url                              | published            | updated              | comment_urls              |
      | Paper A | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00001v1        | 2026-05-10T08:00:00Z | 2026-05-17T08:00:00Z | https://example.com/a     |
      | Paper B | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00002v1        | 2026-05-14T15:00:00Z | 2026-05-16T10:00:00Z | https://example.com/b     |
      | Paper C | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00003v1        | 2026-05-12T09:00:00Z | 2026-05-12T09:00:00Z | https://example.com/c     |
    When the feed is generated
    Then the entry published dates in document order are "2026-05-14T15:00:00Z" then "2026-05-12T09:00:00Z" then "2026-05-10T08:00:00Z"
    And the feed-level updated element value is "2026-05-14T15:00:00Z"

  Scenario Outline: Feed title encodes the category, strict flag, and repository
    Given the environment variable ARXIV_CATEGORY_ID is "<category>"
    And the environment variable ARXIV_CATEGORY_STRICT is "<strict>"
    And the environment variable GITHUB_REPOSITORY is "<repository>"
    And one input article with any valid fields
    When the feed is generated
    Then the feed-level title element value is "<expected_title>"

    Examples:
      | category | strict | repository                | expected_title                               |
      | cs.AI    | false  | owner/code-available-feed | cs.AI strict=false owner/code-available-feed |
      | cs.CV    | true   | exampleuser/my-fork       | cs.CV strict=true exampleuser/my-fork        |

  Scenario: Top-level feed updated is the newest article published date
    Given three input articles:
      | title   | authors      | primary_category | abstract_url                              | published            | updated              | comment_urls              |
      | Paper A | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00001v1        | 2026-05-10T08:00:00Z | 2026-05-10T08:00:00Z | https://example.com/a     |
      | Paper B | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00002v1        | 2026-05-14T15:00:00Z | 2026-05-14T15:00:00Z | https://example.com/b     |
      | Paper C | Test Author  | cs.AI            | https://arxiv.org/abs/0001.00003v1        | 2026-05-12T09:00:00Z | 2026-05-12T09:00:00Z | https://example.com/c     |
    When the feed is generated
    Then the feed-level updated element value is "2026-05-14T15:00:00Z"
