#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

docker compose down || true
docker compose up server --detach --wait
docker compose exec --no-TTY server python -m mypy .
