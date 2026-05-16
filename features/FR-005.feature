@status-done
Feature: FR-005 Weekly storage path and week-rollover archive

  The current week's feed is stored at "docs/arxiv/{category}/atom.xml" where
  {category} is the ARXIV_CATEGORY_ID lowercased. At the start of each run the
  script parses the ISO week number of the newest <entry><published> date in
  the existing atom.xml (if any) and compares it to the ISO week number of
  today. If they differ, the existing file is copied to
  "docs/arxiv/{category}/archive/YYYY-WNN/atom.xml" before being overwritten.
  No archive step is performed on the very first run.

  Background:
    Given the local arxiv fixture server is running
    And the environment variable ARXIV_API_BASE_URL points at the fixture server
    And the environment variable ARXIV_CATEGORY_ID is "cs.AI"
    And the environment variable GITHUB_REPOSITORY is "marcindulak/code-available-feed"
    And the environment variable PIPELINE_TODAY is "2026-05-14"
    And by default the fixture server returns entries that all have a comment URL

  Scenario Outline: The output file path uses a lowercased category
    Given the environment variable ARXIV_CATEGORY_ID is "<configured>"
    When the pipeline runs to completion
    Then the output file path is "<expected_path>"

    Examples:
      | configured | expected_path                |
      | cs.AI      | docs/arxiv/cs.ai/atom.xml    |
      | cs.ai      | docs/arxiv/cs.ai/atom.xml    |
      | CS.CV      | docs/arxiv/cs.cv/atom.xml    |

  Scenario: First run does not create an archive file
    Given no "docs/arxiv/cs.ai/atom.xml" file exists in a fresh temporary directory
    When the pipeline runs to completion
    Then no file exists under "docs/arxiv/cs.ai/archive/"

  Scenario Outline: Existing file from a prior ISO week is archived under that prior week's directory
    Given an existing "docs/arxiv/cs.ai/atom.xml" whose newest entry published date is "<prior_published>"
    And the environment variable PIPELINE_TODAY is "<today>"
    When the pipeline runs to completion
    Then the file "docs/arxiv/cs.ai/archive/<archive_week>/atom.xml" exists
    And the contents of "docs/arxiv/cs.ai/archive/<archive_week>/atom.xml" match the prior contents of "docs/arxiv/cs.ai/atom.xml"

    Examples:
      | prior_published          | today      | archive_week |
      | 2026-05-08T12:00:00Z     | 2026-05-14 | 2026-W19     |
      | 2026-12-31T12:00:00Z     | 2027-01-04 | 2026-W53     |
      | 2027-01-05T12:00:00Z     | 2027-01-14 | 2027-W01     |

  Scenario: Existing file from the current ISO week is not archived
    Given an existing "docs/arxiv/cs.ai/atom.xml" whose newest entry published date is "2026-05-12T12:00:00Z"
    When the pipeline runs to completion
    Then no file exists under "docs/arxiv/cs.ai/archive/"
