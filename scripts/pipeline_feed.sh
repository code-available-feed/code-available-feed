#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Repo-root markers must be present (catches running from a wrong cwd).
for marker in compose.yml src docs; do
    [ -e "${marker}" ] || { echo "$0: must be run from repo root (missing: ${marker})" >&2; exit 1; }
done

# Resolve env, defaulting consistently with src/utils.py.
# Export so child scripts (e.g. validate_atom_xml.sh) inherit the values.
export ARXIV_API_BASE_URL="${ARXIV_API_BASE_URL:-https://export.arxiv.org}"
export ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
ARXIV_CATEGORY_ID_LOWER="$(echo "${ARXIV_CATEGORY_ID}" | tr '[:upper:]' '[:lower:]')"
export ARXIV_CATEGORY_STRICT="${ARXIV_CATEGORY_STRICT:-false}"
export ARXIV_MAX_RESULTS="${ARXIV_MAX_RESULTS:-100}"
export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
export PIPELINE_TODAY="${PIPELINE_TODAY:-}"
export RETRY_BACKOFF_BASE_SECONDS="${RETRY_BACKOFF_BASE_SECONDS:-30}"

PRIOR_ATOM_PATH="docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml"

# Print a notice when no prior atom.xml is present.
# Locally this usually means the user forgot to restore from gh-pages
# (git fetch origin gh-pages && git checkout origin/gh-pages -- docs/).
# In CI the workflow restores from gh-pages before this script runs.
if [ ! -f "${PRIOR_ATOM_PATH}" ]; then
    echo "no prior ${PRIOR_ATOM_PATH} found; treating as first run" >&2
fi

# Parse-only well-formedness check on every pre-existing atom.xml under docs/.
bash scripts/check_atom_xml.sh

docker compose up server --detach --wait
docker compose exec server bash -ci "tree -D -s docs"
docker compose exec \
    --env ARXIV_API_BASE_URL="${ARXIV_API_BASE_URL}" \
    --env ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID}" \
    --env ARXIV_CATEGORY_STRICT="${ARXIV_CATEGORY_STRICT}" \
    --env ARXIV_MAX_RESULTS="${ARXIV_MAX_RESULTS}" \
    --env GITHUB_REPOSITORY="${GITHUB_REPOSITORY}" \
    --env PIPELINE_TODAY="${PIPELINE_TODAY}" \
    --env RETRY_BACKOFF_BASE_SECONDS="${RETRY_BACKOFF_BASE_SECONDS}" \
    server bash -ci "python -m src.pipeline_feed"
docker compose exec server bash -ci "tree -D -s docs"

# Minimal XML well-formedness check on the generated feed.
docker compose exec --no-TTY server bash -ci "
    python -c 'import xml.etree.ElementTree as ET; ET.parse(\"docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml\")'
"

# Newsboat feed validation (FR-010): validate the current feed and the
# lexicographically latest archive, if one exists.
bash scripts/validate_atom_xml.sh --filename "docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml"

LATEST_ARCHIVE="$(docker compose exec --no-TTY server python -c "
import pathlib, sys
sys.path.insert(0, '/app')
from src.utils import find_latest_archive_path
result = find_latest_archive_path(pathlib.Path('docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/archive'))
print(result if result is not None else '', end='')
" 2>/dev/null)"
if [ -n "${LATEST_ARCHIVE}" ]; then
    bash scripts/validate_atom_xml.sh --filename "${LATEST_ARCHIVE}"
fi
