@status-todo
Feature: FR-003 Per-article field extraction from the arxiv API response

  For each article that passes the inclusion filter the pipeline records: the
  title, all author names in document order, the primary category, the arxiv
  abstract page URL (https), the first publication date, the latest version
  date, and all "https://" URLs from the comment in order of appearance with
  trailing punctuation characters from the set ".,;:)]>" stripped from each
  URL.

  Scenario: Extract all recorded fields from a representative API entry
    Given an arxiv API entry fixture file "features/fixtures/entry_two_urls.xml" with:
      | element                                                    | value                                                         |
      | atom:title                                                 | Entity-Consistent Video Generation                            |
      | atom:author[0]/atom:name                                   | Alice Example                                                 |
      | atom:author[1]/atom:name                                   | Bob Sample                                                    |
      | arxiv:primary_category/@term                               | cs.CV                                                         |
      | atom:link[@rel='alternate'][@type='text/html']/@href       | https://arxiv.org/abs/2605.15199v1                            |
      | atom:id                                                    | http://arxiv.org/abs/2605.15199v1                             |
      | atom:published                                             | 2026-05-12T11:30:00Z                                          |
      | atom:updated                                               | 2026-05-12T11:30:00Z                                          |
      | arxiv:comment                                              | Code: https://github.com/foo/bar demo: https://foo.github.io/ |
    When the pipeline extracts article fields from the fixture
    Then the recorded title is "Entity-Consistent Video Generation"
    And the recorded authors in order are "Alice Example" then "Bob Sample"
    And the recorded primary category is "cs.CV"
    And the recorded abstract page URL is "https://arxiv.org/abs/2605.15199v1"
    And the recorded published date is "2026-05-12T11:30:00Z"
    And the recorded updated date is "2026-05-12T11:30:00Z"
    And the recorded comment URLs in order are "https://github.com/foo/bar" then "https://foo.github.io/"

  Scenario: Abstract page URL is taken from the alternate-type link, not the id element
    Given an arxiv API entry whose atom:id is "http://arxiv.org/abs/2605.15199v1"
    And the same entry has atom:link rel "alternate" type "text/html" with href "https://arxiv.org/abs/2605.15199v1"
    When the pipeline extracts article fields
    Then the recorded abstract page URL is "https://arxiv.org/abs/2605.15199v1"
    And the recorded abstract page URL does not start with "http://"

  Scenario: PDF link is not recorded
    Given an arxiv API entry whose atom:link rel "related" type "application/pdf" has href "https://arxiv.org/pdf/2605.15199v1"
    When the pipeline extracts article fields
    Then the recorded fields contain no field equal to "https://arxiv.org/pdf/2605.15199v1"

  Scenario Outline: Trailing punctuation is stripped from each comment URL
    Given an article whose comment is "<comment>"
    When the pipeline extracts the comment URLs
    Then the recorded comment URLs in order are "<urls>"

    Examples:
      | comment                                                                  | urls                                              |
      | available at https://github.com/foo/bar.                                 | https://github.com/foo/bar                        |
      | see https://example.com/x);                                              | https://example.com/x                             |
      | https://a.example/path, and https://b.example/                           | https://a.example/path,then,https://b.example/    |
      | https://example.com/path?q=1&r=2.                                        | https://example.com/path?q=1&r=2                  |

  Scenario: Updated equals published for a v1 article
    Given an arxiv API entry whose atom:published is "2026-05-12T11:30:00Z" and atom:updated is "2026-05-12T11:30:00Z"
    When the pipeline extracts article fields
    Then the recorded published date equals the recorded updated date

  Scenario: Updated differs from published for a v2 revision
    Given an arxiv API entry whose atom:published is "2026-05-08T09:00:00Z" and atom:updated is "2026-05-12T11:30:00Z"
    When the pipeline extracts article fields
    Then the recorded published date is "2026-05-08T09:00:00Z"
    And the recorded updated date is "2026-05-12T11:30:00Z"
