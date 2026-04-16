"""Normalisation des strings : slugification et matching fuzzy Levenshtein."""

import re
import unicodedata

from rapidfuzz import fuzz, process


def strip_accents(text: str) -> str:
    """Retire les accents en préservant la structure ASCII."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def slugify(text: str) -> str:
    """Slugifie pour comparaison : lowercase, ASCII, alphanumérique+tirets."""
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fuzzy_match(
    needle: str,
    haystack: list[str],
    threshold: float = 0.85,
) -> str | None:
    """Retourne la meilleure correspondance dans haystack si ratio ≥ threshold, sinon None.

    Compare sur les slugs normalisés pour ignorer accents et casse.
    """
    if not haystack:
        return None

    needle_slug = slugify(needle)
    # Map slug → valeur originale pour restituer la casse d'origine
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
