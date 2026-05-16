"""Configuration resolution for the arxiv feed pipeline."""

import os


def resolve_category_id() -> str:
    """Return ARXIV_CATEGORY_ID from the environment, defaulting to 'cs.AI'."""
    return os.environ.get("ARXIV_CATEGORY_ID", "cs.AI")


def resolve_strict_mode() -> bool:
    """
    Return True when ARXIV_CATEGORY_STRICT is the case-insensitive literal
    'true'; return False for any other value, including unset.
    """
    return os.environ.get("ARXIV_CATEGORY_STRICT", "").lower() == "true"
