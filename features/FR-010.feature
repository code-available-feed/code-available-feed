@status-todo
Feature: FR-010 Newsboat validation of the generated feed

  A Docker-based validation step starts "python -m http.server" inside the
  compose "server" service to serve "docs/" on a local port, then runs
  "newsboat --execute reload" against the current week's feed URL and (if
  present) the most recent archived feed URL. The validation step fails (and
  no commit is made) if newsboat exits with a non-zero code.

  Newsboat is invoked via "docker compose exec server bash -ci ..." as in
  old/metropolia-torunska-extras/scripts/validate_atom_xml.sh.
  No Dockerfile is used; the newsboat tool is provisioned via the compose
  service definition.

  Scenario: A valid current-week atom.xml passes newsboat validation
    Given a valid atom.xml file at "docs/arxiv/cs.ai/atom.xml"
    And no directory "docs/arxiv/cs.ai/archive/" exists
    When the validation script runs
    Then newsboat exits with code 0
    And the validation script exits with code 0

  Scenario: A malformed current-week atom.xml fails newsboat validation
    Given a malformed atom.xml file at "docs/arxiv/cs.ai/atom.xml"
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
    Then newsboat is invoked against the URL ending in "/arxiv/cs.ai/archive/2026-W19/atom.xml"
    And newsboat is not invoked against any URL ending in "/arxiv/cs.ai/archive/2026-W18/atom.xml"

  Scenario: A valid archive feed but a malformed current-week feed fails the validation step as a whole
    Given a malformed atom.xml file at "docs/arxiv/cs.ai/atom.xml"
    And a valid atom.xml file at "docs/arxiv/cs.ai/archive/2026-W19/atom.xml"
    When the validation script runs
    Then the validation script exits with a non-zero code
