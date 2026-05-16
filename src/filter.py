"""Article inclusion filter for the arxiv feed pipeline."""

import src.config


def include_article(primary_category: str, comment: str | None) -> bool:
    """
    Return True if the article should be included in the feed.

    Both conditions must hold:
    1. Category condition: when strict mode is enabled, the article's primary
       category must match the configured ARXIV_CATEGORY_ID (case-insensitive);
       when strict mode is disabled, any primary category is accepted.
    2. Comment URL condition: the arxiv:comment field must contain at least one
       https:// URL; absent or empty comment fields are treated as no URL.

    Reads ARXIV_CATEGORY_ID and ARXIV_CATEGORY_STRICT from the environment via
    src.config.
    """
    category_id = src.config.resolve_category_id()
    strict_mode = src.config.resolve_strict_mode()

    if strict_mode and primary_category.lower() != category_id.lower():
        return False

    if not comment:
        return False

    return "https://" in comment
