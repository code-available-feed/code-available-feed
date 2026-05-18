@status-done
Feature: FR-010 Newsboat validation of the generated feed

  A Docker-based validation step starts "python -m http.server" inside the
  compose "server" service to serve "docs/" on a local port, then runs
  newsboat once for the current week's feed URL and, if an archive exists,
  once for the most recent archived feed URL. Each invocation uses a separate
  single-entry temporary URL file. This validation runs after feed generation
  and before the no-change byte comparison (FR-006) and before the commit.
  The validation step fails (and no commit is made) if either newsboat
  invocation exits with a non-zero code.

  Scenario: A valid current-week atom.xml passes newsboat validation
    Given a valid atom.xml file at "docs/arxiv/cs.ai/atom.xml"
    And no directory "docs/arxiv/cs.ai/archive/" exists
    When the validation script runs
    Then newsboat exits with code 0
    And the validation script exits with code 0

  Scenario: A current-week atom.xml containing invalid XML fails newsboat validation
    Given a file containing invalid XML at "docs/arxiv/cs.ai/atom.xml"
    When the validation script runs
    Then newsboat exits with a non-zero code
    And the validation script exits with a non-zero code

  Scenario: Both the current-week feed and the most recent archive feed are validated
    Given a valid atom.xml file at "docs/arxiv/cs.ai/atom.xml"
    And a valid atom.xml file at "docs/arxiv/cs.ai/archive/2026-W19/atom.xml"
    When the validation script runs
    Then newsboat exits with code 0 for the URL ending in "/arxiv/cs.ai/atom.xml"
    And newsboat exits with code 0 for the URL ending in "/arxiv/cs.ai/archive/2026-W19/atom.xml"

  Scenario: When several archive weeks exist only the lexicographically latest archive is validated
    Given a valid atom.xml file at "docs/arxiv/cs.ai/atom.xml"
    And a valid atom.xml file at "docs/arxiv/cs.ai/archive/2026-W18/atom.xml"
    And a valid atom.xml file at "docs/arxiv/cs.ai/archive/2026-W19/atom.xml"
    When the validation script runs
    Then the archive invocation URL file contains exactly one entry ending in "/arxiv/cs.ai/archive/2026-W19/atom.xml"

  Scenario: A valid archive feed but a current-week feed containing invalid XML fails the validation step as a whole
    Given a file containing invalid XML at "docs/arxiv/cs.ai/atom.xml"
    And a valid atom.xml file at "docs/arxiv/cs.ai/archive/2026-W19/atom.xml"
    When the validation script runs
    Then the validation script exits with a non-zero code
