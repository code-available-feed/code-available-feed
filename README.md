> Co-Authored-By: Claude

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

GitHub Pages serves `docs/` from the `main` branch; the feed URL is
`https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml`
(e.g. `https://marcindulak.github.io/code-available-feed/arxiv/cs.ai/atom.xml`).

A fork sets `ARXIV_CATEGORY_ID` in its repository Settings → Actions → Variables to target a
different arxiv category without changing any code.
`ARXIV_CATEGORY_STRICT=true` restricts inclusion to articles whose primary category matches
`ARXIV_CATEGORY_ID`; the default `false` includes cross-listed articles.

This service was not reviewed or approved by, nor does it necessarily express or reflect the policies or opinions of, arXiv.

# Usage examples

## Build the Docker image

```bash
docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)
```

## One-time repository setup (GitHub)

After forking or creating the repository, perform these steps once in the GitHub UI:

1. **GitHub Pages**: go to Settings → Pages → Source, select "Deploy from a branch",
   choose branch `main` and folder `/docs`, then click Save.
   The feed becomes available at `https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml`.

2. **Category variable** (optional, defaults to `cs.AI`): go to Settings → Actions → Variables,
   create a variable named `ARXIV_CATEGORY_ID` with the desired arxiv category (e.g. `cs.CV`).

3. **Strict mode** (optional, defaults to `false`): create a variable named `ARXIV_CATEGORY_STRICT`
   and set it to `true` to include only articles whose primary category matches `ARXIV_CATEGORY_ID`.

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
├── Dockerfile.server           # debian:trixie-slim + python (via python-is-python3) + newsboat + behave + mypy (no pip)
├── docs/
│   └── arxiv/
│       └── {category}/
│           ├── atom.xml                # Current week's Atom 1.0 feed
│           └── archive/
│               └── YYYY-WNN/
│                   └── atom.xml        # Prior-week archives
├── features/
│   ├── environment.py          # Behave hooks: skip @status-todo scenarios; restore env vars after each
│   ├── steps/                  # Step definitions (one file per feature group)
│   ├── fixtures/               # Fixture data for determinism and field-extraction tests
│   ├── FR-001.feature          # Fetch current ISO week from arxiv API
│   ├── FR-002.feature          # Article inclusion filter
│   ├── FR-003.feature          # Per-article field extraction
│   ├── FR-004.feature          # Atom 1.0 feed generation
│   ├── FR-005.feature          # Weekly storage path and archive
│   ├── FR-006.feature          # No-change commit guard
│   ├── FR-007.feature          # GitHub Pages configuration (no BDD scenarios)
│   ├── FR-008.feature          # Repository variable resolution
│   ├── FR-009.feature          # Feed self-URL construction
│   ├── FR-010.feature          # Newsboat validation
│   ├── FR-011.feature          # Retry on API failure
│   ├── FR-012.feature          # workflow_dispatch trigger (no BDD scenarios)
│   ├── FR-013.feature          # Diagnostic logging
│   ├── FR-014.feature          # Feed alternate link to the source GitHub repository
│   ├── NFR-001.feature         # Python standard library only (no BDD scenarios)
│   ├── NFR-002.feature         # API rate limiting (no BDD scenarios)
│   ├── NFR-003.feature         # GitHub-hosted runner (no BDD scenarios)
│   ├── NFR-004.feature         # XML escaping correctness
│   ├── NFR-005.feature         # Byte-for-byte deterministic output
│   ├── NFR-006.feature         # README arXiv disclaimer
│   └── NFR-007.feature         # Local testability via scripts (no BDD scenarios)
├── scripts/
│   ├── pipeline_feed.sh        # Run the feed pipeline inside Docker
│   ├── validate_atom_xml.sh    # Validate atom.xml with newsboat inside Docker
│   ├── test_e2e_behave.sh      # Run BDD test suite inside Docker
│   └── test_mypy.sh            # Run mypy type checking inside Docker
└── src/
    ├── __init__.py             # Package marker
    ├── config.py               # Resolve ARXIV_CATEGORY_ID and ARXIV_CATEGORY_STRICT from env
    ├── filter.py               # Article inclusion filter (comment URL presence + optional strict category match)
    └── pipeline_feed.py        # Fetch arxiv API, filter, build Atom 1.0 XML; archiving and diff logging planned
```

## Components

- **Configuration** (`src/config.py`): resolves `ARXIV_CATEGORY_ID` (default `cs.AI`) and
  `ARXIV_CATEGORY_STRICT` (default `false`; case-insensitive; only the literal `true` enables
  strict mode) from the process environment
- **Inclusion filter** (`src/filter.py`): `include_article(primary_category, comment)` returns
  True when both conditions hold: (1) in strict mode the article's primary category matches
  `ARXIV_CATEGORY_ID` case-insensitively; (2) the comment contains at least one `https://` URL
- **Feed pipeline** (`src/pipeline_feed.py`): pages the arxiv API in steps of 2000,
  applies the inclusion filter, generates RFC 4287 Atom XML sorted by published date descending;
  the canonical feed URL is constructed by `build_feed_url(github_repository, category_id)` as
  `https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml` and embedded as both `<feed><id>`
  and `<feed><link rel="self">` in the generated XML;
  a feed-level `<link rel="alternate" href="https://github.com/{owner}/{repo}"/>` is added by
  `build_github_repo_url(github_repository)` to give feed readers a direct link to the pipeline
  source repository;
  archives the prior week's feed before overwriting (`archive_prior_week_feed`);
  compares the generated bytes with the previously committed version (`feeds_are_identical`) and
  prints the git commit message (`build_commit_message`, format `Update YYYY-WNN feed (N articles)`)
  or `no change: feed unchanged` to stdout;
  stdout diff logging (FR-013) is not yet implemented
- **Atom feed** (`docs/arxiv/{category}/atom.xml`): RFC 4287, UTF-8, deterministic byte output;
  one file per ISO calendar week; archived under `archive/YYYY-WNN/`
- **Docker container** (`Dockerfile.server`): `debian:trixie-slim` with `python` (via `python-is-python3`),
  `newsboat`, `python3-behave`, `python3-mypy`; no `pip install` step (stdlib only, NFR-001)
- **GitHub Pages**: serves `docs/` from `main`; `ARXIV_CATEGORY_ID` controls both the API
  query parameter and the feed URL path

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
