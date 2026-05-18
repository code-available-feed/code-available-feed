@status-done
Feature: NFR-007 Feed generation is fully testable locally using scripts

  # Not tested via BDD.
  #
  # NFR-007 specifies:
  #   "The complete feed generation and validation pipeline is exercisable
  #    locally without a GitHub Actions runner using the scripts in scripts/;
  #    the GitHub Actions workflow YAML contains no inline shell logic,
  #    with the narrow exceptions listed below for plumbing that has no
  #    local equivalent".
  #
  # Testing local testability via BDD would be circular: the BDD test suite
  # is itself one of the local testing mechanisms. The scripts are the
  # verification path and the workflow YAML is verified by code review.
  #
  # Verification path:
  #   scripts/pipeline_feed.sh       - generate docs/arxiv/{category}/atom.xml
  #   scripts/validate_atom_xml.sh   - validate the generated feed with newsboat
  #   scripts/deploy_orphan.sh       - publish docs/ to the gh-pages orphan branch
  #   scripts/test_e2e_behave.sh     - run the full BDD test suite
  #   scripts/test_mypy.sh           - run static type checking
  #
  # Permitted inline-YAML exceptions (each has no local equivalent and
  # depends on runner state set by GitHub Actions itself):
  #   (a) restoring repository branch state via `git fetch` + `git checkout`
  #       of another branch into the workflow checkout, so the pipeline can
  #       compare against the previously deployed feed.
  #   (b) listing and downloading prior workflow-run artifacts via the `gh`
  #       CLI when the triggering event is `workflow_dispatch`.
  #   (c) `if:` conditionals on workflow event names.
  # Every other step invokes a script from `scripts/` or uses a GitHub-provided
  # setup action.  Presence of inline shell outside (a)-(c) is caught by code
  # review of the workflow YAML.
  #
  # Local exercise of the pipeline covers both generation and deployment.
  # `scripts/pipeline_feed.sh` runs locally inside Docker.
  # `scripts/deploy_orphan.sh` publishes to gh-pages using the developer's
  # pre-existing git authentication (SSH key, credential helper, or `gh`); CI
  # uses the ephemeral workflow `GITHUB_TOKEN`. No personal access token is
  # required in either path.
