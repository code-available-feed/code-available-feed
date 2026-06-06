#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# --filename <relpath>: path to the Atom feed relative to the repo root (required).
# The expected item count is derived from the feed itself by counting <entry>
# elements using Python inside Docker.

FILENAME=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --filename)
            FILENAME="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [ -z "${FILENAME}" ]; then
    echo "--filename is required" >&2
    exit 1
fi

if [ ! -f "${FILENAME}" ]; then
    echo "${FILENAME} not found" >&2
    exit 1
fi

# --filename is a path relative to the repo root. Inside the container the repo
# is mounted at /app, so the container path is /app/<FILENAME>.
CONTAINER_FILE="/app/${FILENAME}"

# Derive the docs root by stripping everything from /arxiv/ onward, then derive
# the feed path relative to that docs root.
DOCS_DIR_IN_CONTAINER="${CONTAINER_FILE%%/arxiv/*}"
REL_PATH="${CONTAINER_FILE#${DOCS_DIR_IN_CONTAINER}/}"

docker compose up server --detach --wait

# Count <entry> elements using Python inside Docker. If this fails (e.g. the
# feed is malformed XML) the feed is invalid and we exit early.
# Pattern follows scripts/deploy_orphan.sh: outer \" becomes " in the inner
# bash, then the single-quoted python -c argument receives valid Python code.
if ! EXPECTED_ITEM_COUNT="$(docker compose exec --no-TTY server python -c "import xml.etree.ElementTree as ET; root = ET.parse('${CONTAINER_FILE}').getroot(); ns = 'http://www.w3.org/2005/Atom'; print(len(root.findall('{' + ns + '}entry')))")"; then
    echo "${FILENAME}: XML parsing failed, treating feed as invalid" >&2
    exit 1
fi

# Run newsboat inside the container.  PORT, HTTP_PID, URL_FILE, CACHE_FILE,
# SEARCH_HIST, CMD_HIST, NEWSBOAT_OUTPUT, and UNREAD are container-side
# variables (escaped with \$); DOCS_DIR_IN_CONTAINER and REL_PATH are expanded
# by the host shell before the string is sent to the container.
UNREAD="$(docker compose exec --no-TTY server bash -c "
    PORT=\$(python -c 'import socket; s=socket.socket(); s.bind((\"\",0)); p=s.getsockname()[1]; s.close(); print(p)')
    python -m http.server \"\${PORT}\" --bind 127.0.0.1 --directory ${DOCS_DIR_IN_CONTAINER} &
    HTTP_PID=\$!
    sleep 1
    URL_FILE=\$(mktemp)
    CACHE_FILE=\$(mktemp)
    SEARCH_HIST=\$(mktemp)
    CMD_HIST=\$(mktemp)
    echo \"http://127.0.0.1:\${PORT}/${REL_PATH}\" > \"\${URL_FILE}\"
    NEWSBOAT_OUTPUT=\$(LANG=C.UTF-8 newsboat \
        --url-file \"\${URL_FILE}\" \
        --cache-file \"\${CACHE_FILE}\" \
        --search-history-file \"\${SEARCH_HIST}\" \
        --cmdline-history-file \"\${CMD_HIST}\" \
        --execute reload \
        --execute 'print-unread' \
        --quiet 2>&1)
    kill \"\${HTTP_PID}\" 2>/dev/null || true
    rm -f \"\${URL_FILE}\" \"\${CACHE_FILE}\" \"\${SEARCH_HIST}\" \"\${CMD_HIST}\"
    echo \"\${NEWSBOAT_OUTPUT}\" | awk '{print \$1}'
")"

echo "${FILENAME}: expected ${EXPECTED_ITEM_COUNT} items, newsboat reported ${UNREAD:-0} items"
if [ "${UNREAD:-0}" -eq "${EXPECTED_ITEM_COUNT}" ]; then
    exit 0
else
    exit 1
fi
