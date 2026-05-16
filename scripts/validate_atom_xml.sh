#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

if [ ! -f docs/atom.xml ]; then
    echo "docs/atom.xml not found. Run scripts/pipeline_feed.sh first." >&2
    exit 1
fi

docker compose up server --detach --wait
docker compose exec server bash -ci "ls -al docs"
# Start the HTTP server inside the server container serving docs/,
# then validate that atom.xml is accessible and parseable by newsboat.
docker compose exec server bash -ci "
    python -m http.server 8002 --bind 0.0.0.0 --directory /app/docs &
    HTTP_PID=\$!
    sleep 1
    echo 'http://127.0.0.1:8002/atom.xml' > /tmp/atom_test_urls
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
