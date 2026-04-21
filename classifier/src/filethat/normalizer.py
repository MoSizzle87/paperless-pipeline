"""String normalization: slugification and Levenshtein fuzzy matching."""

import re
import unicodedata

from rapidfuzz import fuzz, process


def strip_accents(text: str) -> str:
    """Remove accents while preserving ASCII structure."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def slugify(text: str) -> str:
    """Slugify for comparison: lowercase, ASCII, alphanumeric and hyphens only."""
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fuzzy_match(
    needle: str,
    haystack: list[str],
    threshold: float = 0.85,
) -> str | None:
    """Return the best match in haystack if similarity ratio >= threshold, else None.

    Comparison is performed on normalized slugs to ignore accents and case.
    The original casing of the matched value is preserved in the return value.
    """
    if not haystack:
        return None

    needle_slug = slugify(needle)

    # Map slug → original value to restore original casing
    slug_to_original = {slugify(h): h for h in haystack}

    match = process.extractOne(
        needle_slug,
        list(slug_to_original.keys()),
        scorer=fuzz.ratio,
        score_cutoff=threshold * 100,
    )
    if match is None:
        return None

    best_slug, _score, _idx = match
    return slug_to_original[best_slug]
