"""Step definitions for FR-008: Repository variable resolution."""

import os

from behave import given, then, when

import src.pipeline_feed


@given('the environment variable {name} is ""')
def step_set_env_var_empty(context, name):
    # Specific step for empty string because parse's {value} requires
    # at least one character and would not match an empty-quoted argument.
    if name not in context.env_overrides:
        context.env_overrides[name] = os.environ.get(name)
    os.environ[name] = ""


@given('the environment variable {name} is "{value}"')
def step_set_env_var(context, name, value):
    if name not in context.env_overrides:
        context.env_overrides[name] = os.environ.get(name)
    os.environ[name] = value


@given("the environment variable {name} is unset")
def step_unset_env_var(context, name):
    if name not in context.env_overrides:
        context.env_overrides[name] = os.environ.get(name)
    os.environ.pop(name, None)


@when("the configuration is resolved")
def step_resolve_config(context):
    context.resolved_category_id = src.pipeline_feed.resolve_category_id()
    context.resolved_strict_mode = src.pipeline_feed.resolve_strict_mode()


@then('the resolved category id is "{expected}"')
def step_resolved_category_id(context, expected):
    assert context.resolved_category_id == expected, (
        f"Expected category id {expected!r}, got {context.resolved_category_id!r}"
    )


@then("the resolved strict-mode flag is {expected}")
def step_resolved_strict_flag(context, expected):
    expected_bool = expected == "true"
    assert context.resolved_strict_mode == expected_bool, (
        f"Expected strict mode {expected_bool}, got {context.resolved_strict_mode}"
    )


@when("the configuration category id is resolved")
def step_resolve_category_id_only(context):
    # Capture the raised exception so the Then step can assert on its type.
    # Calling resolve_strict_mode() is skipped here because the invalid-id
    # scenario exercises only the category-id validation path.
    context.resolve_exception = None
    try:
        context.resolved_category_id = src.pipeline_feed.resolve_category_id()
    except Exception as exc:
        context.resolve_exception = exc


@then("resolve_category_id raises ValueError")
def step_resolve_category_id_raises_value_error(context):
    assert isinstance(context.resolve_exception, ValueError), (
        "Expected resolve_category_id to raise ValueError, got "
        f"{type(context.resolve_exception).__name__}: {context.resolve_exception!r}"
    )


@when("the continue-on-api-error flag is resolved")
def step_resolve_continue_on_api_error(context):
    context.resolved_continue_on_api_error = (
        src.pipeline_feed.resolve_continue_on_api_error()
    )


@then("the resolved continue-on-api-error flag is {expected}")
def step_resolved_continue_on_api_error(context, expected):
    expected_bool = expected == "true"
    assert context.resolved_continue_on_api_error == expected_bool, (
        f"Expected continue-on-api-error {expected_bool}, "
        f"got {context.resolved_continue_on_api_error}"
    )


@when("the staleness days configuration is resolved")
def step_resolve_staleness_days(context):
    # _validate_staleness_days raises ValueError on invalid input; the Then
    # step asserts on the captured outcome (parsed value or exception type).
    context.staleness_exception = None
    context.staleness_parsed = None
    value = os.environ.get("ARXIV_MAX_STALENESS_DAYS", "-1")
    try:
        context.staleness_parsed = src.pipeline_feed._validate_staleness_days(value)
    except ValueError as exc:
        context.staleness_exception = exc


@then("ARXIV_MAX_STALENESS_DAYS is accepted")
def step_staleness_accepted(context):
    assert context.staleness_exception is None, (
        f"Expected ARXIV_MAX_STALENESS_DAYS to be accepted, got exception: "
        f"{context.staleness_exception!r}"
    )


@then("ARXIV_MAX_STALENESS_DAYS is rejected with ValueError")
def step_staleness_rejected(context):
    assert isinstance(context.staleness_exception, ValueError), (
        "Expected ARXIV_MAX_STALENESS_DAYS to raise ValueError, got "
        f"{type(context.staleness_exception).__name__}: {context.staleness_exception!r}"
    )
