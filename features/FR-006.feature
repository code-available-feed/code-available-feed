@status-done
Feature: FR-006 No-change commit guard

  The scenarios here cover:
  (1) the script-level change-detection decision (changed vs. no change), and
  (2) the commit message construction function, which reads the generated
  atom.xml to count <entry> elements and derive the ISO week from the newest
  <entry><published> date.
  The no-change byte comparison runs after newsboat validation (FR-010) has
  already passed. The git commit invocation itself is part of the GitHub
  Actions workflow and is not covered by BDD scenarios.

  Background:
    Given the environment variable ARXIV_CATEGORY_ID is "cs.AI"

  Scenario: Identical bytes produce a "no change" decision
    Given an existing "docs/arxiv/cs.ai/atom.xml" file with known content
    And a freshly generated atom.xml with byte-for-byte identical content
    When the commit-guard step compares the two files
    Then the commit-guard step reports "no change"

  Scenario: One differing byte produces a "changed" decision
    Given an existing "docs/arxiv/cs.ai/atom.xml" file with known content
    And a freshly generated atom.xml that differs from the existing file by one byte
    When the commit-guard step compares the two files
    Then the commit-guard step reports "changed"

  Scenario: No prior file produces a "changed" decision (first run)
    Given no "docs/arxiv/cs.ai/atom.xml" file exists in a fresh temporary directory
    And a freshly generated atom.xml has been written to that path
    When the commit-guard step runs
    Then the commit-guard step reports "changed"

  Scenario: Commit message uses singular "article" when the feed contains exactly one entry
    Given an atom.xml containing 1 entry whose newest published date is "2026-05-14T15:00:00Z"
    When the commit message is constructed from the atom.xml
    Then the commit message is "Update 2026-W20 feed (1 article)"

  Scenario: Commit message uses plural "articles" when the feed contains more than one entry
    Given an atom.xml containing 3 entries whose newest published date is "2026-05-14T15:00:00Z"
    When the commit message is constructed from the atom.xml
    Then the commit message is "Update 2026-W20 feed (3 articles)"

  Scenario: Commit message ISO week is derived from the newest entry published date across a year boundary
    Given an atom.xml containing 2 entries whose newest published date is "2026-12-31T12:00:00Z"
    When the commit message is constructed from the atom.xml
    Then the commit message is "Update 2026-W53 feed (2 articles)"

