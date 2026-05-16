@status-todo
Feature: FR-006 No-change commit guard and commit message format

  The workflow commits "docs/arxiv/{category}/atom.xml" and the newly created
  archive file (if any) with the message "Update YYYY-WNN feed (X articles)".
  If the generated atom.xml is byte-for-byte identical to the version already
  in the repository, no commit is made. The git push to main itself is part
  of the GitHub Actions workflow and is not covered by these scenarios. What
  is covered is the local script-level decision of whether a commit should be
  made and the format of the commit message string.

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

  Scenario Outline: Commit message format is "Update YYYY-WNN feed (X articles)"
    Given the ISO week of today is "<iso_week>"
    And the article count in the generated feed is <count>
    When the commit message is built
    Then the commit message equals "<expected>"

    Examples:
      | iso_week | count | expected                          |
      | 2026-W20 | 100   | Update 2026-W20 feed (100 articles) |
      | 2026-W01 | 1     | Update 2026-W01 feed (1 articles)   |
      | 2027-W53 | 0     | Update 2027-W53 feed (0 articles)   |
