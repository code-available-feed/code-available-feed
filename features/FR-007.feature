@status-done
Feature: FR-007 GitHub Pages serving of the docs directory

  # Not tested via BDD.
  #
  # FR-007 specifies:
  #   "GitHub Pages is configured to serve the docs/ directory from the main
  #    branch; the feed URL for account {user} with repository named {repo} is
  #    https://{user}.github.io/{repo}/arxiv/{category}/atom.xml".
  #
  # The "configure GitHub Pages" half is a repository setting in the GitHub UI,
  # not application code, so it cannot be exercised locally. The URL pattern
  # half is identical to the self-link URL that FR-009 constructs and is
  # already covered there. Adding scenarios here would either duplicate FR-009
  # or test GitHub's own static-file serving, which is out of scope.
  #
  # Verification path: the deployed feed URL is reachable in the browser after
  # the workflow commits to main; this verification is performed manually by
  # the maintainer.
