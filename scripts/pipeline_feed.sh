#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Resolve env, defaulting consistently with src/config.py.
ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
ARXIV_CATEGORY_ID_LOWER="$(echo "${ARXIV_CATEGORY_ID}" | tr '[:upper:]' '[:lower:]')"

docker compose up server --detach --wait
docker compose exec server bash -ci "ls -al docs"
docker compose exec server bash -ci "python -m src.pipeline_feed"
docker compose exec server bash -ci "ls -al docs"

# FR-010 stopgap: XML well-formedness check on the generated feed.
# Closes the validation gap between this iteration and FR-010 (which adds
# full newsboat-based validation in scripts/validate_atom_xml.sh).
docker compose exec --no-TTY server bash -ci "
    python -c 'import xml.etree.ElementTree as ET; ET.parse(\"docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml\")'
"
