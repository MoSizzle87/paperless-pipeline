"""Unit tests for filethat.normalizer."""

import pytest

from filethat.normalizer import fuzzy_match, slugify, strip_accents


class TestStripAccents:
    def test_basic_accents(self) -> None:
        assert strip_accents("éèêë") == "eeee"

    def test_cedilla(self) -> None:
        assert strip_accents("ç") == "c"

    def test_no_accents_unchanged(self) -> None:
        assert strip_accents("hello") == "hello"

    def test_empty_string(self) -> None:
        assert strip_accents("") == ""

    def test_mixed(self) -> None:
        assert strip_accents("Électricité") == "Electricite"


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("EDF") == "edf"

    def test_accents(self) -> None:
        assert slugify("Électricité de France") == "electricite-de-france"

    def test_special_characters(self) -> None:
        assert slugify("BNP Paribas") == "bnp-paribas"

    def test_slashes(self) -> None:
        assert slugify("Pôle Emploi / France Travail") == "pole-emploi-france-travail"

    def test_multiple_spaces(self) -> None:
        assert slugify("EDF  SA") == "edf-sa"

    def test_leading_trailing_hyphens(self) -> None:
        assert slugify("  EDF  ") == "edf"

    def test_empty_string(self) -> None:
        assert slugify("") == ""

    def test_numbers(self) -> None:
        assert slugify("3F") == "3f"

    def test_apostrophe(self) -> None:
        assert slugify("Caisse d'Allocations Familiales") == "caisse-d-allocations-familiales"

    def test_dots(self) -> None:
        assert slugify("E.D.F.") == "e-d-f"


class TestFuzzyMatch:
    def test_exact_match(self) -> None:
        assert fuzzy_match("EDF", ["EDF", "ENGIE", "CAF"], 0.85) == "EDF"

    def test_case_insensitive(self) -> None:
        assert fuzzy_match("edf", ["EDF", "ENGIE"], 0.85) == "EDF"

    def test_accent_insensitive(self) -> None:
        assert (
            fuzzy_match("Electricite de France", ["Électricité de France"], 0.85)
            == "Électricité de France"
        )

    def test_no_match_below_threshold(self) -> None:
        assert fuzzy_match("inconnu-xyz-abc", ["EDF", "ENGIE", "CAF"], 0.95) is None

    def test_empty_haystack(self) -> None:
        assert fuzzy_match("EDF", [], 0.85) is None

    def test_returns_original_casing(self) -> None:
        result = fuzzy_match("bnp paribas", ["BNP Paribas", "LCL"], 0.85)
        assert result == "BNP Paribas"

    def test_threshold_boundary(self) -> None:
        # Exact match should always pass any threshold
        assert fuzzy_match("EDF", ["EDF"], 1.0) == "EDF"

    def test_low_threshold_allows_partial(self) -> None:
        assert fuzzy_match("EDF SA", ["EDF", "ENGIE"], 0.5) == "EDF"

    def test_multiple_candidates_returns_best(self) -> None:
        result = fuzzy_match("Societe Generale", ["Société Générale", "Société Marseillaise"], 0.7)
        assert result == "Société Générale"
