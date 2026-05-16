@status-todo
Feature: NFR-007 Feed generation is fully testable locally using scripts

  # Not tested via BDD.
  #
  # NFR-007 specifies:
  #   "The complete feed generation and validation pipeline is exercisable
  #    locally without a GitHub Actions runner using the scripts in scripts/;
  #    the GitHub Actions workflow YAML contains no inline shell logic".
  #
  # Testing local testability via BDD would be circular: the BDD test suite
  # is itself one of the four local testing mechanisms. The scripts are the
  # verification path and the workflow YAML is verified by code review.
  #
  # Verification path:
  #   scripts/pipeline_feed.sh     - generate docs/arxiv/{category}/atom.xml
  #   scripts/validate_atom_xml.sh - validate the generated feed with newsboat
  #   scripts/test_e2e_behave.sh   - run the full BDD test suite
  #   scripts/test_mypy.sh         - run static type checking
  #
  # All four scripts are inspected during code review to confirm that the
  # GitHub Actions workflow YAML contains no inline shell logic beyond
  # invoking these scripts or GitHub-provided setup actions.
