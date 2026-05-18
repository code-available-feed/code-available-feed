"""
Behave environment hooks.

Scenarios from features tagged @status-todo are skipped because their
implementation is deferred to a future iteration.
Scenarios from @status-active and @status-done features run normally.

Environment variables set by step definitions are restored to their
original values after each scenario to prevent state leakage between
scenarios.
"""

import os
import pathlib
import sys

# Allow step definitions to import from src/ when behave runs from /app.
sys.path.insert(0, str(pathlib.Path(".").resolve()))
# Allow step definitions to import from features/ (e.g. fixtures package).
sys.path.insert(0, str(pathlib.Path(".").resolve() / "features"))

_RUNNABLE_STATUSES = frozenset({"status-active", "status-done"})


def before_scenario(context, scenario):
    feature_tags = frozenset(scenario.feature.tags)
    if not feature_tags & _RUNNABLE_STATUSES:
        scenario.skip("Feature not yet implemented (@status-todo)")
    # Tracks env vars modified by step definitions so after_scenario can
    # restore them.  Maps variable name to original value (None = was absent).
    context.env_overrides = {}
    context.articles = []
    context.fixture_server = None
    context.run_dir = None
    context.validation_dir = None
    context.validation_results = None


def after_scenario(context, scenario):
    for key, original_value in context.env_overrides.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value

    if context.fixture_server is not None:
        context.fixture_server.stop()
        context.fixture_server = None
