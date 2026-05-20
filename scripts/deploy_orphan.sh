#!/usr/bin/env bash

set -Eeuo pipefail

echo "Executing: $0"

# Repo-root markers.
for marker in compose.yml src docs; do
    [ -e "${marker}" ] || { echo "$0: must be run from repo root (missing: ${marker})" >&2; exit 1; }
done

# Resolve env.
ARXIV_CATEGORY_ID="${ARXIV_CATEGORY_ID:-cs.AI}"
ARXIV_CATEGORY_ID_LOWER="$(echo "${ARXIV_CATEGORY_ID}" | tr '[:upper:]' '[:lower:]')"
ATOM_PATH="docs/arxiv/${ARXIV_CATEGORY_ID_LOWER}/atom.xml"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
GITHUB_SHA_EFFECTIVE="${GITHUB_SHA:-$(git rev-parse HEAD)}"

# Capture the host repo's origin URL before cd'ing to /tmp.
# Used for two things: (1) consistency check vs GITHUB_REPOSITORY in the
# local case, (2) actual remote URL for the local push.
PARENT_ORIGIN_URL="$(git config --get remote.origin.url)"

# Local-only: assert that GITHUB_REPOSITORY matches the dev's origin URL.
# In CI, GITHUB_TOKEN is present and we build a fresh token URL, so the
# parent origin URL is not used for the push and no check is needed.
if [ -z "${GITHUB_TOKEN:-}" ]; then
    if [[ "${PARENT_ORIGIN_URL}" != *"github.com/${GITHUB_REPOSITORY}"* ]] \
       && [[ "${PARENT_ORIGIN_URL}" != *"github.com:${GITHUB_REPOSITORY}"* ]]; then
        echo "$0: GITHUB_REPOSITORY=${GITHUB_REPOSITORY} does not match origin URL ${PARENT_ORIGIN_URL}" >&2
        exit 1
    fi
fi

# Reconstruct the commit message subject inside the container, calling the
# same Python module the pipeline uses. Single source of truth for FR-006.
docker compose up server --detach --wait
COMMIT_SUBJECT="$(docker compose exec --no-TTY server bash -ci "python -c 'from src.pipeline_feed import build_commit_message; import pathlib; print(build_commit_message(pathlib.Path(\"${ATOM_PATH}\")))'")"

# Build the orphan commit in a temp dir on the host.
mkdir /tmp/orphan-deploy
cp --recursive docs /tmp/orphan-deploy/docs

# Remove the docs/.gitignore placeholder copied over from main so its
# '*' rule does not block git add, and so the placeholder does not leak
# to the gh-pages branch.
rm -f /tmp/orphan-deploy/docs/.gitignore

cd /tmp/orphan-deploy
git init
git checkout --orphan gh-pages
git add docs/
git commit --message "${COMMIT_SUBJECT}" \
           --message "From main@${GITHUB_SHA_EFFECTIVE}"

# Remote URL: CI uses workflow token, local uses dev's existing auth.
if [ -n "${GITHUB_TOKEN:-}" ]; then
    git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
else
    git remote add origin "${PARENT_ORIGIN_URL}"
fi

git push --force origin gh-pages
