#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Resolve env, defaulting consistently with src/utils.py.
ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
ARXIV_CATEGORY_ID_LOWER="$(echo "${ARXIV_CATEGORY_ID}" | tr '[:upper:]' '[:lower:]')"
ATOM_PATH="docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml"

if [ ! -f "${ATOM_PATH}" ]; then
    echo "${ATOM_PATH} not found. Run scripts/pipeline_feed.sh first." >&2
    exit 1
fi

docker compose up server --detach --wait
docker compose exec server bash -ci "tree -D -s docs"
# Start the HTTP server inside the server container serving docs/,
# then validate that atom.xml is accessible and parseable by newsboat.
docker compose exec server bash -ci "
    python -m http.server 8002 --bind 0.0.0.0 --directory /app/docs &
    HTTP_PID=\$!
    sleep 1
    echo 'http://127.0.0.1:8002/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml' > /tmp/atom_test_urls
    LANG=C.UTF-8 newsboat \
        --url-file /tmp/atom_test_urls \
        --cache-file /tmp/atom_test_cache.db \
        --search-history-file /tmp/atom_test_search_hist \
        --cmdline-history-file /tmp/atom_test_cmdline_hist \
        --execute reload \
        --quiet
    NEWSBOAT_RC=\$?
    kill \"\$HTTP_PID\" 2>/dev/null || true
    rm -f \
        /tmp/atom_test_urls \
        /tmp/atom_test_cache.db \
        /tmp/atom_test_search_hist \
        /tmp/atom_test_cmdline_hist
    exit \"\$NEWSBOAT_RC\"
"
