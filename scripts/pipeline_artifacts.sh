#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Repo-root markers must be present (catches running from a wrong cwd).
for marker in compose.yml src docs; do
    [ -e "${marker}" ] || { echo "$0: must be run from repo root (missing: ${marker})" >&2; exit 1; }
done

# Resolve env, defaulting consistently with src/utils.py.
# Export so child scripts (e.g. pipeline_feed.sh, validate_atom_xml.sh) inherit the values.
export ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
ARXIV_CATEGORY_ID_LOWER="$(echo "${ARXIV_CATEGORY_ID}" | tr '[:upper:]' '[:lower:]')"
export ARXIV_CATEGORY_STRICT="${ARXIV_CATEGORY_STRICT:-false}"
PRIOR_ATOM_PATH="docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml"

# Print a notice when no prior atom.xml is present.
# Locally this usually means the user forgot to restore from gh-pages
# (git fetch origin gh-pages && git checkout origin/gh-pages -- docs/).
# In CI the workflow restores from gh-pages before this script runs.
if [ ! -f "${PRIOR_ATOM_PATH}" ]; then
    echo "no prior ${PRIOR_ATOM_PATH} found; treating as first run" >&2
fi

# Post-restore consistency check on every restored atom.xml under docs/.
bash scripts/check_restored_atom_xml.sh

# TODO(FR-010): validate the newest docs/arxiv/<cat>/archive/YYYY-WNN/atom.xml
# with newsboat (HTTP + feed-reader semantics) before any pipeline work begins,
# to catch a corrupt previously-deployed feed early.

# Generate docs/arxiv/{category}/atom.xml.
# pipeline_feed.sh additionally runs a stopgap XML well-formedness check
# on the generated file (see scripts/pipeline_feed.sh).
bash scripts/pipeline_feed.sh
