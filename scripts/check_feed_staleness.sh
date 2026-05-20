#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Repo-root markers must be present (catches running from a wrong cwd).
for marker in compose.yml src docs; do
    [ -e "${marker}" ] || { echo "$0: must be run from repo root (missing: ${marker})" >&2; exit 1; }
done

export ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
export ARXIV_MAX_STALENESS_DAYS="${ARXIV_MAX_STALENESS_DAYS:--1}"
export PIPELINE_TODAY="${PIPELINE_TODAY:-}"

echo "ARXIV_CATEGORY_ID=${ARXIV_CATEGORY_ID}"
echo "ARXIV_MAX_STALENESS_DAYS=${ARXIV_MAX_STALENESS_DAYS}"
echo "PIPELINE_TODAY=${PIPELINE_TODAY}"

docker compose up server --detach --wait
docker compose exec \
    --env ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID}" \
    --env ARXIV_MAX_STALENESS_DAYS="${ARXIV_MAX_STALENESS_DAYS}" \
    --env PIPELINE_TODAY="${PIPELINE_TODAY}" \
    server bash -ci "python -m src.check_feed_staleness"
