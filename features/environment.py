"""
Behave environment hooks.

Scenarios from features tagged @status-todo are skipped because their
implementation is deferred to a future iteration.
Scenarios from @status-active and @status-done features run normally.
"""

_RUNNABLE_STATUSES = frozenset({"status-active", "status-done"})


def before_scenario(context, scenario):
    feature_tags = frozenset(scenario.feature.tags)
    if not feature_tags & _RUNNABLE_STATUSES:
        scenario.skip("Feature not yet implemented (@status-todo)")
