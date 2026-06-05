> Co-Authored-By: Claude

> Disclaimer:
> This service was not reviewed or approved by, nor does it necessarily express or reflect the policies or opinions of, arXiv.

# Functionality overview

This repository is a configurable template for the Atom feed of arXiv articles that have code available.
The goal is to offer replacements for the "papers with code" web feed offered until the [mid-2025](https://github.com/paperswithcode/paperswithcode-data/issues/121).

To configure your own feed serving, fork the https://github.com/code-available-feed/code-available-feed repository and set GitHub Actions variables.
The feed for the desired arXiv category will be served on GitHub Pages.

# Available feeds

See [https://code-available-feed.github.io/code-available-feed](https://code-available-feed.github.io/code-available-feed) for the sorted list of available feeds.
If you serve a feed using this project, consider making a pull request to add your feed to this list.

> [!NOTE]
Currently it's [not possible](https://github.com/orgs/community/discussions/79137) to create two forks of the same repo, so one GitHub user can host only one feed.

# Usage examples

## GitHub Pages setup (one-time)

1. Fork the https://github.com/code-available-feed/code-available-feed repository.

2. In your fork configure Settings → Secrets and Variables -> Actions → Variables -> Repository Variables:

   a. `ARXIV_CATEGORY_ID` (defaults to `cs.AI`): set to any arXiv category, e.g. `cs.CV`.

   b. `ARXIV_CATEGORY_STRICT` (defaults to `false`): set to `true` to restrict to only articles whose primary category matches `ARXIV_CATEGORY_ID`.

   c. `ARXIV_CONTINUE_ON_API_ERROR` (defaults to `true` in the workflow): set to `false` to fail the workflow immediately on any arXiv API error instead of continuing silently. The goal of the silent continuation on arXiv API errors is to avoid frequent pipeline failure email notifications, and instead alert on feed staleness (see the `ARXIV_MAX_STALENESS_DAYS` variable).

   d. `ARXIV_MAX_STALENESS_DAYS` (defaults to `10` in the workflow): the workflow fails with a staleness alert when the newest feed entry is more than this many calendar days old (e.g. with the default of `10`, an age of `10` days passes and `11` days fails). Set to `-1` to disable the check. Raise this value for low-volume categories where multi-day gaps without new articles are normal.

   e. `ARXIV_MAX_BACKFILL_DAYS` (defaults to `8`): the rolling fetch window in days.
The API query fetches articles from `[today - ARXIV_MAX_BACKFILL_DAYS, today]`.
Must be a positive integer (minimum 1).
With the default of 8, Monday's run covers the full prior ISO week plus one extra day, recovering articles submitted after Thursday 14:00 ET that the arXiv announcement schedule delays past the ISO week boundary.

   f. `ARXIV_MAX_RESULTS` (defaults to `50`): number of articles requested per arxiv API page.

   g. `RETRY_BACKOFF_BASE_SECONDS` (defaults to `60`): base duration in seconds for exponential retry backoff on the first API page. The N-th retry waits `N × RETRY_BACKOFF_BASE_SECONDS` seconds.

3. Enable GitHub Actions in Settings -> Actions -> General -> Allow {owner}, and select non-{owner}, actions and reusable workflows ->  Allow actions created by GitHub.

4. Run the `pipeline_feed` workflow at least once (via the Actions tab or wait for the daily schedule).
   The first successful `deploy_orphan` run creates the `gh-pages` branch.

5. In repository Settings → Pages, set Source to *Deploy from a branch*, Branch to `gh-pages`, Folder to `/docs`.

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
bash scripts/validate_atom_xml.sh --filename docs/arxiv/cs.ai/atom.xml
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
The 7-day `arxiv-feed` artifact is the rollback window: re-run `deploy_orphan` via `workflow_dispatch` with an older successful `pipeline_feed` run.
Beyond 7 days, recovery regenerates the feed from the current arXiv state.

# Implementation overview

## Project structure

```
├── compose.yml                   # Docker service: build from Dockerfile.server, mount repo at /app
├── Dockerfile.server             # debian with apt-get packages for python (no pip)
├── docs/
│   └── arxiv/
│       └── {category}/
│           ├── atom.xml          # Current week's Atom 1.0 feed
│           └── archive/          # Prior-weeks archives
│               └── YYYY-WNN/
│                   └── atom.xml
├── features/
│   ├── environment.py            # Behave hooks: skip @status-todo scenarios, restore envs
│   ├── fixtures/                 # Fixture data for determinism and field-extraction tests
│   └── steps/                    # Step definitions (one file per feature group)
├── scripts/
│   ├── build_docker_image.sh     # Build the server Docker image
│   ├── check_atom_xml.sh         # Parse-only XML well-formedness check on every docs/**/atom.xml
│   ├── check_feed_staleness.sh   # Fail if the feed recently has no new items
│   ├── deploy_orphan.sh          # Force-push docs/ to the gh-pages orphan branch
│   ├── pipeline_feed.sh          # Generate and validate feed inside Docker
│   ├── validate_atom_xml.sh      # Validate atom.xml with newsboat inside Docker
│   ├── test_e2e_behave.sh        # Run BDD test suite inside Docker
│   └── test_mypy.sh              # Run mypy type checking inside Docker
└── src/
    ├── __init__.py               # Package marker
    └── pipeline_feed.py          # All feed creation and management logic
```

# Abandoned ideas

See [REQUIREMENTS.md](./REQUIREMENTS.md).
