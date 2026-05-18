#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

export BUILDKIT_PROGRESS=plain
docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)
