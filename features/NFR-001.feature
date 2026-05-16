@status-todo
Feature: NFR-001 Pipeline imports only the Python standard library

  The pipeline script uses only the Python standard library. No third-party
  packages are installed and no third-party top-level modules are imported by
  any source file under src/.

  Scenario: No source file under src/ imports a third-party top-level module
    Given the list of every Python source file under "src/"
    When each file's top-level import statements are parsed
    Then every imported top-level module is part of the Python standard library

  Scenario: No "pip install" or equivalent line appears in compose.yml
    Given the file "compose.yml"
    When its contents are read
    Then the contents contain no occurrence of "pip install"
    And the contents contain no occurrence of "requirements.txt"

  Scenario: No requirements.txt or pyproject.toml ships in the repository
    Given the repository root directory
    When the file listing is taken
    Then no file named "requirements.txt" exists at the repository root
    And no file named "pyproject.toml" exists at the repository root
