@status-todo
Feature: NFR-005 Byte-for-byte deterministic XML output for identical input

  The XML generator must produce byte-for-byte identical output for identical
  input. Articles are always written in published-descending order, XML
  attributes are always inserted in the same fixed order, the output
  encoding is always UTF-8 with the declaration "<?xml version='1.0'
  encoding='UTF-8'?>", and no timestamp or run-id is embedded in the output.

  Scenario: Two runs over the same input produce byte-identical output
    Given a fixed set of input articles loaded from "features/fixtures/articles_three.json"
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "marcindulak/code-available-feed"
    When the feed generator runs and writes to "/tmp/run_a.xml"
    And the feed generator runs again and writes to "/tmp/run_b.xml"
    Then the SHA-256 hash of "/tmp/run_a.xml" equals the SHA-256 hash of "/tmp/run_b.xml"

  Scenario: Re-ordering input articles does not change the output (sort is deterministic)
    Given a fixed set of input articles loaded from "features/fixtures/articles_three.json"
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "marcindulak/code-available-feed"
    When the feed generator runs and writes to "/tmp/run_in_order.xml"
    And the same input articles are shuffled into a different order
    And the feed generator runs and writes to "/tmp/run_shuffled.xml"
    Then the SHA-256 hash of "/tmp/run_in_order.xml" equals the SHA-256 hash of "/tmp/run_shuffled.xml"

  Scenario: The XML declaration is exactly "<?xml version='1.0' encoding='UTF-8'?>"
    Given any non-empty input article set
    When the feed generator runs
    Then the first line of the output equals "<?xml version='1.0' encoding='UTF-8'?>"

  Scenario: No wall-clock timestamp leaks into the output
    Given a fixed set of input articles loaded from "features/fixtures/articles_three.json"
    When the feed generator runs at wall-clock time "2026-05-14T10:00:00Z" and writes to "/tmp/run_at_10.xml"
    And the feed generator runs at wall-clock time "2026-05-14T18:00:00Z" and writes to "/tmp/run_at_18.xml"
    Then the SHA-256 hash of "/tmp/run_at_10.xml" equals the SHA-256 hash of "/tmp/run_at_18.xml"
