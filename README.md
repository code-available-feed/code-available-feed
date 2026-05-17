> Co-Authored-By: Claude

> Disclaimer:
> This service was not reviewed or approved by, nor does it necessarily express or reflect the policies or opinions of, arXiv.

# Functionality overview

Weekly Atom 1.0 feed of arxiv articles that list a `https://` URL in their `arxiv:comment` field,
generated from the arxiv API without scraping.

The pipeline runs daily via GitHub Actions, queries the arxiv API for all articles submitted to the
configured category during the current ISO calendar week (Monday–Sunday UTC), keeps only those whose
`arxiv:comment` contains at least one `https://` URL, and writes `docs/arxiv/{category}/atom.xml`.
Each feed entry contains: title (prefixed with the primary category in brackets), all authors,
primary category, arxiv abstract URL, first publication date, latest revision date,
and the extracted `https://` URLs one per line.

At the end of each calendar week the current feed is archived to
`docs/arxiv/{category}/archive/YYYY-WNN/atom.xml` and the new week's data overwrites the live file.
The generated XML is validated with newsboat before any commit is made.

GitHub Pages serves `docs/` from the `gh-pages` orphan branch; the feed URL is
`https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml`
(e.g. `https://marcindulak.github.io/code-available-feed/arxiv/cs.ai/atom.xml`).

A fork sets `ARXIV_CATEGORY_ID` in its repository Settings → Actions → Variables to target a
different arxiv category without changing any code.
`ARXIV_CATEGORY_STRICT=true` restricts inclusion to articles whose primary category matches
`ARXIV_CATEGORY_ID`; the default `false` includes cross-listed articles.

# Usage examples

## Build the Docker image

```bash
docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)
```

## GitHub Pages setup

1. Fork or create the repository and push to GitHub.
2. Run the `pipeline_artifacts` and `deploy_orphan` workflows at least once
   (manually via the Actions tab or wait for the daily schedule).
   The first successful `deploy_orphan` run creates the `gh-pages` branch.
3. In repository Settings → Pages, set Source to *Deploy from a branch*,
   Branch to `gh-pages`, Folder to `/docs`.

## Category and strict-mode variables (optional)

In Settings → Actions → Variables:

1. **Category variable** (defaults to `cs.AI`): create a variable named `ARXIV_CATEGORY_ID`
   with the desired arxiv category (e.g. `cs.CV`).
2. **Strict mode** (defaults to `false`): create a variable named `ARXIV_CATEGORY_STRICT`
   and set it to `true` to include only articles whose primary category matches `ARXIV_CATEGORY_ID`.

## Rolling back a bad deploy

The `gh-pages` branch is force-pushed on every successful `deploy_orphan` run, so its git
history holds only the most recent orphan commit.
The 7-day retention on the `arxiv-feeds` artifact is the de-facto rollback window: to restore
a known-good feed, re-run `deploy_orphan` via `workflow_dispatch` while specifying an older
successful `pipeline_artifacts` run.
Beyond 7 days, recovery requires regenerating the feed from the current arxiv state, which
produces the latest week's data but loses any per-day intermediate state.

## Run the feed pipeline locally

```bash
GITHUB_REPOSITORY=owner/repo bash scripts/pipeline_feed.sh
```

The feed is written to `docs/arxiv/cs.ai/atom.xml` (or the path matching the configured category).

## Validate the generated feed

```bash
bash scripts/validate_atom_xml.sh
```

# Implementation overview

## File structure

```
├── compose.yml                 # Docker service: build from Dockerfile.server, mount repo at /app
├── Dockerfile.server           # debian:trixie-slim + apt packages for python, TLS, feed validation, and testing (no pip)
├── docs/
│   └── arxiv/
│       └── {category}/
│           ├── atom.xml                # Current week's Atom 1.0 feed
│           └── archive/
│               └── YYYY-WNN/
│                   └── atom.xml        # Prior-week archives
├── features/
│   ├── environment.py          # Behave hooks: skip @status-todo scenarios; restore env vars after each
│   ├── fixtures/               # Fixture data for determinism and field-extraction tests
│   └── steps/                  # Step definitions (one file per feature group)
├── scripts/
│   ├── check_restored_atom_xml.sh # Post-restore well-formedness check on every docs/**/atom.xml
│   ├── deploy_orphan.sh        # Force-push docs/ to the gh-pages orphan branch
│   ├── pipeline_artifacts.sh   # End-to-end pipeline driver (restore-check + generation)
│   ├── pipeline_feed.sh        # Run the feed pipeline inside Docker
│   ├── validate_atom_xml.sh    # Validate atom.xml with newsboat inside Docker
│   ├── test_e2e_behave.sh      # Run BDD test suite inside Docker
│   └── test_mypy.sh            # Run mypy type checking inside Docker
└── src/
    ├── __init__.py             # Package marker
    ├── utils.py                # Shared utilities: category/strict-mode config resolution, article inclusion filter, commit message builder
    └── pipeline_feed.py        # Fetch arxiv API, filter, build Atom 1.0 XML, archive prior week, emit UTC JSON diagnostic logs
```

## Components

- **Shared utilities** (`src/utils.py`): resolves `ARXIV_CATEGORY_ID` (default `cs.AI`) and
  `ARXIV_CATEGORY_STRICT` (default `false`; case-insensitive; only the literal `true` enables
  strict mode) from the process environment;
  `include_article(primary_category, comment)` returns True when both conditions hold: (1) in
  strict mode the article's primary category matches `ARXIV_CATEGORY_ID` case-insensitively;
  (2) the comment contains at least one `https://` URL;
  `build_commit_message(path)` and `build_commit_message_from_bytes(bytes)` construct the commit
  message string (format `Update YYYY-WNN feed (N articles)`) from a generated `atom.xml`
- **Feed pipeline** (`src/pipeline_feed.py`): pages the arxiv API in steps of `ARXIV_MAX_RESULTS`
  (configurable via `ARXIV_MAX_RESULTS`; large values trigger HTTP 429 from the arxiv API),
  applies the inclusion filter, generates RFC 4287 Atom XML sorted by published date descending;
  the canonical feed URL is constructed by `build_feed_url(github_repository, category_id)` as
  `https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml` and embedded as both `<feed><id>`
  and `<feed><link rel="self">` in the generated XML;
  a feed-level `<link rel="alternate" href="https://github.com/{owner}/{repo}"/>` is added by
  `build_github_repo_url(github_repository)` to give feed readers a direct link to the pipeline
  source repository;
  archives the prior week's feed before overwriting (`archive_prior_week_feed`);
  compares the generated bytes with the prior version and logs the commit message
  (format `Update YYYY-WNN feed (N articles)`) or `no change: feed unchanged`;
  all diagnostic output is written as UTC JSON (INFO to stdout, ERROR to stderr);
  FR-013 unified diff logging is not yet implemented
- **Atom feed** (`docs/arxiv/{category}/atom.xml`): RFC 4287, UTF-8, deterministic byte output;
  one file per ISO calendar week; archived under `archive/YYYY-WNN/`
- **Docker container** (`Dockerfile.server`): `debian:trixie-slim` with apt packages for Python, TLS, feed validation, and testing; no `pip install` step (stdlib only, NFR-001)
- **GitHub Pages**: serves `docs/` from the `gh-pages` orphan branch
  (force-pushed on each successful deploy by `scripts/deploy_orphan.sh`);
  `ARXIV_CATEGORY_ID` controls both the API query parameter and the feed URL path

# Running tests

## Integration tests (BDD)

```bash
bash scripts/test_e2e_behave.sh
```

## Type checking

```bash
bash scripts/test_mypy.sh
```

# Abandoned ideas

See the `Abandoned Ideas` section of `REQUIREMENTS.md` for design-phase ideas considered and
rejected before implementation began.

**Direct commits to `main` for feed updates**: rejected after initial implementation in favour of
the orphan-branch model.
Committing `docs/arxiv/atom.xml` to `main` mixed generated content with source code and grew
`main`'s git history unboundedly.
The orphan-branch model keeps `main` clean and lets the deploy step force-push without
accumulating history.
