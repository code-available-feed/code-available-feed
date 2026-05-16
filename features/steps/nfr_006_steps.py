"""Step definitions for NFR-006: README.md contains the arXiv brand disclaimer."""

import pathlib

from behave import given, then, when


@given("the repository root directory")
def step_given_repo_root(context):
    context.repo_root = pathlib.Path(".")


@when("the file listing is taken")
def step_when_file_listing(context):
    context.file_listing = list(context.repo_root.iterdir())


@then('a file named "README.md" exists at the repository root')
def step_then_readme_exists(context):
    assert (context.repo_root / "README.md").exists(), (
        "README.md not found at repository root"
    )


@given('the file "README.md" at the repository root')
def step_given_readme_file(context):
    context.readme_path = pathlib.Path(".") / "README.md"


@when("its contents are read")
def step_when_contents_read(context):
    context.readme_contents = context.readme_path.read_text(encoding="utf-8")


@then('the contents contain the exact string "{text}"')
def step_then_contains_text(context, text):
    assert text in context.readme_contents, (
        f"README.md does not contain the required text.\nExpected: {text!r}"
    )
