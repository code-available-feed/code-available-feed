"""Step definitions for FR-001: Fetch the current ISO week from the arxiv API."""

import contextlib
import io
import os
import pathlib
import tempfile
import typing
import urllib.parse

from behave import given, then, when

import src.pipeline_feed
from fixtures.arxiv_fixture_server import ArxivFixtureServer


class PipelineResult(typing.NamedTuple):
    """In-process replacement for subprocess.CompletedProcess used by BDD steps."""

    returncode: int
    stdout: str
    stderr: str


@given("the local arxiv fixture server is running")
def step_start_fixture_server(context):
    context.fixture_server = ArxivFixtureServer()


@given("the environment variable ARXIV_API_BASE_URL points at the fixture server")
def step_set_arxiv_api_base_url(context):
    name = "ARXIV_API_BASE_URL"
    if name not in context.env_overrides:
        context.env_overrides[name] = os.environ.get(name)
    os.environ[name] = context.fixture_server.url


@given("by default the fixture server returns entries that all have a comment URL")
def step_fixture_default_comment_url(context):
    # ArxivFixtureServer defaults to 10 entries, all with a comment URL.
    # This step is present in the Background to document the precondition.
    pass


@given('no "{filepath}" file exists in a fresh temporary directory')
def step_create_fresh_run_dir(context, filepath):
    context.run_dir = pathlib.Path(tempfile.mkdtemp())
    assert not (context.run_dir / filepath).exists(), (
        f"Unexpected file {filepath} in fresh temp dir {context.run_dir}"
    )


@given(
    'the fixture server returns {n_entries:d} entries for query parameter "start={start_value:d}"'
)
def step_fixture_set_entries_for_start(context, n_entries, start_value):
    context.fixture_server.set_response(
        start=start_value, status=200, n_entries=n_entries
    )


@given(
    "the fixture server responds with HTTP {status:d} and {n_entries:d} entries"
    " to the first request"
)
def step_fixture_respond_to_first_request(context, status, n_entries):
    # "first request" is always the request with start=0.
    context.fixture_server.set_response(
        start=0, status=status, n_entries=n_entries
    )


@when("the pipeline runs to completion")
def step_run_pipeline(context):
    """
    Invoke src.pipeline_feed.main() in-process against a temporary base_dir.

    Capturing stdout/stderr via contextlib.redirect_* works because
    _setup_logging() clears prior handlers on every call (see
    src/pipeline_feed.py); the new handlers bind to the redirected streams.
    """
    if context.run_dir is None:
        context.run_dir = pathlib.Path(tempfile.mkdtemp())
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            returncode = src.pipeline_feed.main(base_dir=context.run_dir)
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 1
    context.pipeline_result = PipelineResult(
        returncode=returncode,
        stdout=stdout_buf.getvalue(),
        stderr=stderr_buf.getvalue(),
    )


@then('the fixture server received at least one request with path "{path}"')
def step_fixture_received_request_with_path(context, path):
    requests = context.fixture_server.get_requests()
    assert requests, "Fixture server received no requests"
    paths = [urllib.parse.urlparse(req).path for req in requests]
    assert any(p == path for p in paths), (
        f"No request with path {path!r}; received paths: {paths}"
    )


@then('the first request query string contains "{substring}"')
def step_first_request_query_contains(context, substring):
    requests = context.fixture_server.get_requests()
    assert requests, "Fixture server received no requests"
    query = urllib.parse.urlparse(requests[0]).query
    assert substring in query, (
        f"First request query {query!r} does not contain {substring!r}\n"
        f"pipeline stdout: {context.pipeline_result.stdout}\n"
        f"pipeline stderr: {context.pipeline_result.stderr}"
    )


@then("the fixture server received exactly {n:d} request")
@then("the fixture server received exactly {n:d} requests")
def step_fixture_received_exactly_n_requests(context, n):
    requests = context.fixture_server.get_requests()
    assert len(requests) == n, (
        f"Expected {n} request(s), got {len(requests)}: {requests}"
    )


@then('the second request query string contains "{substring}"')
def step_second_request_query_contains(context, substring):
    requests = context.fixture_server.get_requests()
    assert len(requests) >= 2, (
        f"Expected at least 2 requests, got {len(requests)}"
    )
    query = urllib.parse.urlparse(requests[1]).query
    assert substring in query, (
        f"Second request query {query!r} does not contain {substring!r}"
    )


@then("the pipeline exit code is non-zero")
def step_pipeline_exit_nonzero(context):
    assert context.pipeline_result.returncode != 0, (
        f"Expected non-zero exit code, got {context.pipeline_result.returncode}\n"
        f"stdout: {context.pipeline_result.stdout}\n"
        f"stderr: {context.pipeline_result.stderr}"
    )


@then("the pipeline exit code is 0")
def step_pipeline_exit_zero(context):
    assert context.pipeline_result.returncode == 0, (
        f"Expected exit code 0, got {context.pipeline_result.returncode}\n"
        f"stdout: {context.pipeline_result.stdout}\n"
        f"stderr: {context.pipeline_result.stderr}"
    )


@then('no file "{filepath}" was written by this run')
def step_no_file_written(context, filepath):
    full_path = context.run_dir / filepath
    assert not full_path.exists(), (
        f"Expected no file at {full_path}, but it exists"
    )
