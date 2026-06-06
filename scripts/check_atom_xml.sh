#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Checks that every atom.xml under docs/ is well-formed XML using Python's
# xml.etree.ElementTree. Lighter than validate_atom_xml.sh (no HTTP server,
# no newsboat); use this for a quick parse-only sanity check.
#
# Runs inside the server container because Python is provisioned there.
docker compose up server --detach --wait
docker compose exec --no-TTY server python -c "
import pathlib, sys, xml.etree.ElementTree as ET
for f in pathlib.Path('docs').rglob('atom.xml'):
    try:
        ET.parse(str(f))
    except Exception:
        print(f'atom.xml is malformed: {f}', file=sys.stderr)
        sys.exit(1)
"
