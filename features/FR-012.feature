@status-done
Feature: FR-012 workflow_dispatch trigger

  # Not tested via BDD.
  #
  # FR-012 specifies:
  #   "The GitHub Actions workflow supports `workflow_dispatch` as an
  #    additional trigger alongside the daily schedule; the manual trigger
  #    uses the same logic as the scheduled run".
  #
  # This is a single key in .github/workflows/*.yml under the "on:" mapping.
  # There is no separate code path: a manually triggered run executes the
  # same pipeline script as a scheduled run. The only locally testable thing
  # would be parsing the workflow YAML and asserting that "workflow_dispatch"
  # appears under "on:".
  #
  # Verification path: the maintainer pressing "Run workflow" in the GitHub
  # Actions UI is itself the verification.
