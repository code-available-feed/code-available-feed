@status-todo
Feature: NFR-001 Pipeline imports only the Python standard library

  # Not tested via BDD.
  #
  # NFR-001 specifies:
  #   "The pipeline script uses only the Python standard library; no
  #    third-party packages are imported by any source file under src/".
  #
  # A BDD scenario would parse import statements from source files and
  # cross-reference them against the standard library module list. That
  # list is version-dependent and maintaining it is more fragile than a
  # code review. Additionally, the Docker image built from Dockerfile.server
  # installs no third-party Python packages, so any third-party import would
  # raise an ImportError at runtime, making violations self-evident.
  #
  # Verification path: all Python files under src/ are inspected during code
  # review to confirm that only standard library modules are imported; the
  # production Docker environment enforces the constraint at runtime because
  # no pip install step is present.
