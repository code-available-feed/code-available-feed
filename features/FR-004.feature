@status-todo
Feature: FR-004 Atom 1.0 feed generation

  The pipeline generates an Atom 1.0 feed (RFC 4287) from the collected
  articles. Articles are sorted by first arxiv publication date descending
  (newest first). The top-level feed updated value is the published date of
  the first article in that order.

  Background:
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable FEED_URL is "https://marcindulak.github.io/code-available-feed/arxiv/cs.ai/atom.xml"

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
    Given one input article with primary_category "cs.AI" and title "A Paper Title"
    When the feed is generated
    Then the entry has title "[cs.AI] A Paper Title"

  Scenario: Articles are sorted by published descending
    Given three input articles with published dates:
      | published            |
      | 2026-05-10T08:00:00Z |
      | 2026-05-14T15:00:00Z |
      | 2026-05-12T09:00:00Z |
    When the feed is generated
    Then the entry published dates in document order are "2026-05-14T15:00:00Z" then "2026-05-12T09:00:00Z" then "2026-05-10T08:00:00Z"

  Scenario: A same-week revision does not change article position
    Given three input articles:
      | published            | updated              |
      | 2026-05-10T08:00:00Z | 2026-05-10T08:00:00Z |
      | 2026-05-14T15:00:00Z | 2026-05-15T10:00:00Z |
      | 2026-05-12T09:00:00Z | 2026-05-12T09:00:00Z |
    When the feed is generated
    Then the entry published dates in document order are "2026-05-14T15:00:00Z" then "2026-05-12T09:00:00Z" then "2026-05-10T08:00:00Z"

  Scenario: Top-level feed updated is the newest article published date
    Given three input articles with published dates:
      | published            |
      | 2026-05-10T08:00:00Z |
      | 2026-05-14T15:00:00Z |
      | 2026-05-12T09:00:00Z |
    When the feed is generated
    Then the feed-level updated element value is "2026-05-14T15:00:00Z"
