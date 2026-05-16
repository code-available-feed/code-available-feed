@status-todo
Feature: NFR-003 GitHub-hosted runner is ubuntu-24.04

  # Not tested via BDD.
  #
  # NFR-003 specifies:
  #   "The GitHub Actions workflow targets a GitHub-hosted runner
  #    (ubuntu-24.04) free".
  #
  # The only locally testable thing would be parsing the workflow YAML and
  # asserting that "runs-on" equals "ubuntu-24.04". That is trivial config
  # inspection of a single field and CLAUDE.md explicitly excludes it.
  #
  # Verification path: the runner image is visible in the GitHub Actions run
  # log of every scheduled workflow execution.
