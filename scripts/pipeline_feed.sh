#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Resolve env, defaulting consistently with src/utils.py.
# Export so child scripts (e.g. validate_atom_xml.sh) inherit the values.
export ARXIV_API_BASE_URL="${ARXIV_API_BASE_URL:-https://export.arxiv.org}"
export ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
ARXIV_CATEGORY_ID_LOWER="$(echo "${ARXIV_CATEGORY_ID}" | tr '[:upper:]' '[:lower:]')"
export ARXIV_CATEGORY_STRICT="${ARXIV_CATEGORY_STRICT:-false}"
export ARXIV_MAX_RESULTS="${ARXIV_MAX_RESULTS:-100}"
export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
export PIPELINE_TODAY="${PIPELINE_TODAY:-}"
export RETRY_BACKOFF_BASE_SECONDS="${RETRY_BACKOFF_BASE_SECONDS:-10}"

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

# Full newsboat-based feed validation (FR-010 stopgap).
bash scripts/validate_atom_xml.sh
