#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Post-restore consistency check: every atom.xml under docs/ must be
# well-formed XML. Catches a partial gh-pages restore (e.g. runner killed
# mid-checkout, or a developer's local docs/ left in a half-applied state).
#
# Runs inside the server container because Python is provisioned there.
docker compose up server --detach --wait
docker compose exec --no-TTY server bash -ci '
    set -e
    for f in $(find docs -name atom.xml 2>/dev/null); do
        python -c "import xml.etree.ElementTree as ET; ET.parse(\"$f\")" \
            || { echo "restored atom.xml is malformed: $f" >&2; exit 1; }
    done
'
