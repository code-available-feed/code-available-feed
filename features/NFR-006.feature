@status-todo
Feature: NFR-006 README contains the arXiv brand disclaimer

  The repository's README.md must include the disclaimer required by the
  arXiv brand guidelines:
  "This service was not reviewed or approved by, nor does it necessarily
  express or reflect the policies or opinions of, arXiv."

  Scenario: README.md exists at the repository root
    Given the repository root directory
    When the file listing is taken
    Then a file named "README.md" exists at the repository root

  Scenario: README.md contains the exact arXiv disclaimer sentence
    Given the file "README.md" at the repository root
    When its contents are read
    Then the contents contain the exact string "This service was not reviewed or approved by, nor does it necessarily express or reflect the policies or opinions of, arXiv."
