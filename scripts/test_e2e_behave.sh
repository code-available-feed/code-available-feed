#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

docker compose down || true
docker compose up --detach --wait
docker compose exec server bash -ci "behave"
