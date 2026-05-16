@status-todo
Feature: NFR-002 At least 5 seconds between consecutive arxiv API requests

  # Not tested via BDD.
  #
  # NFR-002 specifies:
  #   "Each arxiv API request is preceded by at least a 5-second sleep".
  #
  # Exercising this with a real wall-clock wait would add at least 5 seconds
  # per pagination step to the test suite. The user has decided that this
  # requirement is verified by code review rather than by a BDD scenario,
  # and that the rate-limit behaviour does not need to be reproved at the
  # behavioural level here.
  #
  # Verification path: the inter-request sleep call is inspected during code
  # review of the pipeline source; the production runtime exercises the
  # full sleep every day on the GitHub Actions runner.
