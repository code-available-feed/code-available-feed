> Co-Authored-By: Claude

> Disclaimer:
> This service was not reviewed or approved by, nor does it necessarily express or reflect the policies or opinions of, arXiv.

# Functionality overview

This repository is a configurable template for the Atom feed of arXiv articles that have code available.
The goal is to offer replacements for the "papers with code" web feed offered until the [mid-2025](https://github.com/paperswithcode/paperswithcode-data/issues/121).

To configure your own feed serving, fork this repository and set GitHub Actions variables.
The feed for the desired arXiv category will be served on GitHub Pages.

# Sorted list of available feeds

- [https://marcindulak.github.io/code-available-feed-cs-ai/arxiv/cs.ai/atom.xml](https://marcindulak.github.io/code-available-feed-cs-ai/arxiv/cs.ai/atom.xml) - Computer Science - cs.AI - Artificial Intelligence (primary and secondary category matches)

# Usage examples

## GitHub Pages setup (one-time)

> [!NOTE]
Choose the appropriate name of the fork if you plan to host more than one feed repo.
See the points below to understand this setup!

1. Fork the repository.

2. In Settings → Actions → Variables:

   a. `ARXIV_CATEGORY_ID` (defaults to `cs.AI`): set to any arXiv category, e.g. `cs.CV`.

   b. `ARXIV_CATEGORY_STRICT` (defaults to `false`): set to `true` to restrict to only articles whose primary category matches `ARXIV_CATEGORY_ID`.

3. Run the `pipeline_feed` workflow at least once (via the Actions tab or wait for the daily schedule).
   The first successful `deploy_orphan` run creates the `gh-pages` branch.

4. In repository Settings → Pages, set Source to *Deploy from a branch*, Branch to `gh-pages`, Folder to `/docs`.

After setup, the feed URL is `https://{owner}.github.io/{repo}/arxiv/{category}/atom.xml`
(e.g. `https://marcindulak.github.io/code-available-feed-cs-ai/arxiv/cs.ai/atom.xml`).

## Local development

Build the Docker image:

```bash
bash scripts/build_docker_image.sh
```

Run the pipeline:

```bash
ARXIV_CATEGORY_ID=cs.AI ARXIV_CATEGORY_STRICT=false \
GITHUB_REPOSITORY=marcindulak/code-available-feed-cs-ai bash scripts/pipeline_feed.sh
```

Validate the generated feed:

```bash
ARXIV_CATEGORY_ID=cs.AI bash scripts/validate_atom_xml.sh
```

## Running tests

### Integration tests (BDD)

```bash
bash scripts/test_e2e_behave.sh
```

### Type checking

```bash
bash scripts/test_mypy.sh
```

## Rolling back a bad deploy

The `gh-pages` branch holds only the most recent orphan commit (force-pushed on each deploy).
The 7-day `arxiv-feeds` artifact is the rollback window: re-run `deploy_orphan` via `workflow_dispatch` with an older successful `pipeline_feed` run.
Beyond 7 days, recovery regenerates the feed from the current arXiv state.

# Implementation overview

## Project structure

```
├── compose.yml                   # Docker service: build from Dockerfile.server, mount repo at /app
├── Dockerfile.server             # debian with apt packages for python (no pip)
├── docs/
│   └── arxiv/
│       └── {category}/
│           ├── atom.xml          # Current week's Atom 1.0 feed
│           └── archive/          # Prior-weeks archives
│               └── YYYY-WNN/
│                   └── atom.xml
├── features/
│   ├── environment.py            # Behave hooks: skip @status-todo scenarios; restore env vars after each
│   ├── fixtures/                 # Fixture data for determinism and field-extraction tests
│   └── steps/                    # Step definitions (one file per feature group)
├── scripts/
│   ├── build_docker_image.sh   # Build the server Docker image
│   ├── check_atom_xml.sh       # Parse-only XML well-formedness check on every docs/**/atom.xml
│   ├── deploy_orphan.sh        # Force-push docs/ to the gh-pages orphan branch
│   ├── pipeline_feed.sh        # Generate and validate feed inside Docker
│   ├── validate_atom_xml.sh    # Validate atom.xml with newsboat inside Docker
│   ├── test_e2e_behave.sh      # Run BDD test suite inside Docker
│   └── test_mypy.sh            # Run mypy type checking inside Docker
└── src/
    ├── __init__.py             # Package marker
    ├── utils.py                # Config resolution, article filter, archive path lookup, commit message builder
    └── pipeline_feed.py        # Fetch, filter, build Atom XML, archive, emit JSON logs
```

`src/pipeline_feed.py` pages the arXiv API, applies the article code availability inclusion filter, writes RFC 4287 Atom XML sorted by published date descending, and archives the prior week's feed at the new week start.
Diagnostic output is UTC JSON (INFO to stdout, ERROR to stderr).
`Dockerfile.server` provides Python, newsboat, behave, and mypy via `apt` with no `pip install`.

# Abandoned ideas

See [REQUIREMENTS.md](./REQUIREMENTS.md).
