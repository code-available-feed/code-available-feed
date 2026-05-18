#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Checks that every atom.xml under docs/ is well-formed XML using Python's
# xml.etree.ElementTree. Lighter than validate_atom_xml.sh (no HTTP server,
# no newsboat); use this for a quick parse-only sanity check.
#
# Runs inside the server container because Python is provisioned there.
docker compose up server --detach --wait
docker compose exec --no-TTY server bash -ci '
    set -e
    for f in $(find docs -name atom.xml 2>/dev/null); do
        python -c "import xml.etree.ElementTree as ET; ET.parse(\"$f\")" \
            || { echo "atom.xml is malformed: $f" >&2; exit 1; }
    done
'
