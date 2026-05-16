#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

docker compose up server --detach --wait
docker compose exec server bash -ci "ls -al docs"
docker compose exec server bash -ci "python -m src.pipeline_feed"
docker compose exec server bash -ci "ls -al docs"
