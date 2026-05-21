@status-done
Feature: FR-004 Atom 1.0 feed generation

  The pipeline generates an Atom 1.0 feed (RFC 4287) from the collected
  articles. Articles are sorted by first arxiv publication date descending
  (newest first). The top-level feed updated value is the published date of
  the first article in that order. Each entry's <content type="html"> is a
  structured HTML block with Authors, Abstract, and Comments sections labeled
  with <h3> headings; the Authors line uses "First Author et al." when there
  are three or more authors.

  Background:
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "owner/code-available-feed"

  Scenario: Each entry contains the required Atom elements in the required form
    Given one input article with:
      | field                  | value                                                                   |
      | title                  | Entity-Consistent Video Generation                                      |
      | authors                | Alice Example, Bob Sample                                               |
      | primary_category       | cs.CV                                                                   |
      | abstract_url           | https://arxiv.org/abs/0000.00001v1                                      |
      | published              | 2026-05-12T11:30:00Z                                                    |
      | updated                | 2026-05-12T11:30:00Z                                                    |
      | abstract               | We propose a method for entity-consistent video generation.             |
      | comment                | Code: https://code.example.com/foo/bar demo: https://demo.example.com/ |
      | comment_urls           | https://code.example.com/foo/bar, https://demo.example.com/            |
    When the feed is generated
    Then the entry has title "[cs.CV] Entity-Consistent Video Generation"
    And the entry has author names "Alice Example" then "Bob Sample" in document order
    And the entry has category element with term "cs.CV" and scheme "http://arxiv.org/schemas/atom"
    And the entry has id "https://arxiv.org/abs/0000.00001v1"
    And the entry has link rel "alternate" type "text/html" with href "https://arxiv.org/abs/0000.00001v1"
    And the entry has published "2026-05-12T11:30:00Z"
    And the entry has updated "2026-05-12T11:30:00Z"
    And the entry content type is "html" with text
      """
      <h3>Authors:</h3>
      <p>Alice Example, Bob Sample</p>
      <h3>Abstract:</h3>
      <p>We propose a method for entity-consistent video generation.</p>
      <h3>Comments:</h3>
      <p>Code: https://code.example.com/foo/bar demo: https://demo.example.com/</p>
      """

  Scenario: Three or more authors are credited with et al. in the content Authors line
    Given one input article with:
      | field                  | value                                           |
      | title                  | A Multi-Author Paper                            |
      | authors                | Alice Example, Bob Sample, Carol White          |
      | primary_category       | cs.AI                                           |
      | abstract_url           | https://arxiv.org/abs/0000.00002v1              |
      | published              | 2026-05-12T11:30:00Z                            |
      | updated                | 2026-05-12T11:30:00Z                            |
      | abstract               | A paper with three authors.                     |
      | comment                | Code: https://code.example.com/test             |
      | comment_urls           | https://code.example.com/test                   |
    When the feed is generated
    Then the entry content type is "html" with text
      """
      <h3>Authors:</h3>
      <p>Alice Example et al.</p>
      <h3>Abstract:</h3>
      <p>A paper with three authors.</p>
      <h3>Comments:</h3>
      <p>Code: https://code.example.com/test</p>
      """

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
