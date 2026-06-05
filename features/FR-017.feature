@status-todo
Feature: FR-017 Processed dict persistence

  The pipeline persists the cascade outcome for each article in a
  <code-available-feed:processed> extension element inside atom.xml.
  On subsequent runs, previously processed articles are not re-enriched:
  articles with a stored non-empty repo_found_in are included directly,
  and articles with a stored empty repo_found_in are excluded directly.
  The processed dict is pruned to entries whose updated date falls within
  the rolling retention window [today - ARXIV_MAX_BACKFILL_DAYS, today].

  Scenario: load_processed returns empty dict when atom.xml does not exist
    Given no atom.xml file exists at the expected path
    When the processed dict is loaded
    Then the processed dict is empty

  Scenario: load_processed returns empty dict when atom.xml has no processed element
    Given an atom.xml file with entries but no processed element
    When the processed dict is loaded
    Then the processed dict is empty

  Scenario: load_processed parses the processed element from atom.xml
    Given an atom.xml file with a processed element containing:
      | url                                    | updated                  | repo_found_in | repo_urls                              |
      | https://arxiv.example.com/abs/0001v1   | 2026-06-01T00:00:00Z     | comment       | https://code.example.com/user/repo     |
      | https://arxiv.example.com/abs/0002v1   | 2026-06-02T00:00:00Z     |               |                                        |
    When the processed dict is loaded with start date "2026-05-25" and end date "2026-06-05"
    Then the processed dict has 2 entries
    And the entry for "https://arxiv.example.com/abs/0001v1" has repo_found_in "comment"
    And the entry for "https://arxiv.example.com/abs/0002v1" has repo_found_in ""

  Scenario: load_processed filters entries outside the retention window
    Given an atom.xml file with a processed element containing:
      | url                                    | updated                  | repo_found_in | repo_urls                              |
      | https://arxiv.example.com/abs/0001v1   | 2026-05-20T00:00:00Z     | comment       | https://code.example.com/user/repo     |
      | https://arxiv.example.com/abs/0002v1   | 2026-06-02T00:00:00Z     | abstract      | https://code.example.com/other/repo    |
    When the processed dict is loaded with start date "2026-06-01" and end date "2026-06-05"
    Then the processed dict has 1 entry
    And the entry for "https://arxiv.example.com/abs/0002v1" has repo_found_in "abstract"

  Scenario: Previously processed article with non-empty repo_found_in is not re-enriched
    Given a processed dict entry for "https://arxiv.example.com/abs/0001v1" with repo_found_in "comment" and repo_urls "https://code.example.com/user/repo"
    And an article fetched from the API with abstract_url "https://arxiv.example.com/abs/0001v1"
    When the pipeline applies the processed dict to the article
    Then the article repo_found_in is "comment"
    And the article repo_urls contains "https://code.example.com/user/repo"
    And no enrichment cascade runs for this article

  Scenario: Previously processed article with empty repo_found_in is excluded without re-enrichment
    Given a processed dict entry for "https://arxiv.example.com/abs/0002v1" with repo_found_in "" and repo_urls ""
    And an article fetched from the API with abstract_url "https://arxiv.example.com/abs/0002v1"
    When the pipeline applies the processed dict to the article
    Then the article repo_found_in is ""
    And no enrichment cascade runs for this article

  Scenario: build_feed includes the processed element in the feed XML
    Given a list of filtered articles with repo_found_in set
    And a processed dict with 2 entries
    When build_feed is called with the articles and processed dict
    Then the generated atom.xml contains a "code-available-feed:processed" element
    And the processed element has 2 child "code-available-feed:article" elements

  Scenario: Processed element children are sorted by url for determinism
    Given a processed dict with entries for "https://arxiv.example.com/abs/0002v1" and "https://arxiv.example.com/abs/0001v1"
    When build_feed is called with the processed dict
    Then the first processed child has url "https://arxiv.example.com/abs/0001v1"
    And the second processed child has url "https://arxiv.example.com/abs/0002v1"

  Scenario: write_processed_element updates existing atom.xml without touching entries
    Given an atom.xml file with 3 feed entries and a processed element with 1 entry
    And an updated processed dict with 2 entries
    When write_processed_element is called
    Then the atom.xml still has 3 feed entries
    And the processed element now has 2 child elements

  Scenario: write_processed_element does nothing when atom.xml does not exist
    Given no atom.xml file exists at the expected path
    And a processed dict with 1 entry
    When write_processed_element is called
    Then no atom.xml file is created
