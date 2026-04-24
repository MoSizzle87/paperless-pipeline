from __future__ import annotations

from pathlib import Path

import pytest

from filethat.classify import ClassificationResult
from filethat.config import Config
from filethat.organize import build_target_path, slugify


def make_config(language: str = "fr", tmp_path: Path | None = None) -> Config:
    cfg = Config.model_validate(
        {
            "language": language,
            "referential": {
                "document_types": [
                    {"key": "invoice", "fr": "Facture", "en": "Invoice"},
                    {"key": "tax", "fr": "Fiscal", "en": "Tax"},
                ],
                "correspondents": ["EDF"],
            },
        }
    )
    if tmp_path:
        cfg.paths.library = tmp_path / "library"
    return cfg


def make_result(**kwargs) -> ClassificationResult:
    defaults = dict(
        document_type="invoice",
        correspondent="EDF",
        document_date="2024-01-15",
        title="Facture janvier 2024",
        language="fr",
        confidence=0.95,
        reasoning="Clear invoice",
        new_correspondent=False,
    )
    defaults.update(kwargs)
    return ClassificationResult.model_validate(defaults)


# --- slugify ---

def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_accents():
    assert slugify("Relevé Décembre") == "releve-decembre"


def test_slugify_special_chars():
    assert slugify("Avis 2024/01 — Taxes!") == "avis-2024-01-taxes"


def test_slugify_max_length():
    assert len(slugify("a" * 100)) <= 40


def test_slugify_collapse_consecutive():
    result = slugify("hello  --  world")
    assert "--" not in result
    assert "hello" in result
    assert "world" in result


def test_slugify_strip_leading_trailing_hyphens():
    result = slugify("---hello---")
    assert not result.startswith("-")
    assert not result.endswith("-")


def test_slugify_empty():
    assert slugify("") == ""


def test_slugify_numbers():
    assert slugify("2024-01-15") == "2024-01-15"


# --- build_target_path ---

def test_build_target_path_fr_label(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result()
    path = build_target_path(result, config)
    assert "Facture" in str(path)


def test_build_target_path_en_label(tmp_path):
    config = make_config("en", tmp_path)
    result = make_result()
    path = build_target_path(result, config)
    assert "Invoice" in str(path)
    assert "Facture" not in str(path)


def test_build_target_path_date_prefix(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_date="2024-01-15")
    path = build_target_path(result, config)
    assert "2024-01" in str(path)


def test_build_target_path_nodate(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_date=None)
    path = build_target_path(result, config)
    assert "nodate" not in path.name
    assert "Facture" in path.name


# --- naming convention: segment omission ---

def test_naming_all_segments_present(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_date="2025-10-01", correspondent="EDF", title="Relevé mensuel octobre")
    path = build_target_path(result, config)
    assert path.name == "2025-10_Facture_edf_releve-mensuel-octobre.pdf"


def test_naming_no_date(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_date=None, correspondent="EDF", title="Relevé mensuel octobre")
    path = build_target_path(result, config)
    assert path.name == "Facture_edf_releve-mensuel-octobre.pdf"
    assert "nodate" not in path.name


def test_naming_unknown_correspondent(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_date="2025-10-01", correspondent="Unknown", title="Relevé mensuel octobre")
    path = build_target_path(result, config)
    assert path.name == "2025-10_Facture_releve-mensuel-octobre.pdf"
    assert "unknown" not in path.name.lower()


def test_naming_no_date_unknown_correspondent(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_date=None, correspondent="Unknown", title="Relevé mensuel octobre")
    path = build_target_path(result, config)
    assert path.name == "Facture_releve-mensuel-octobre.pdf"


def test_naming_other_type_fallback_fr(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(document_type="other", document_date="2025-10-01", correspondent="Unknown", title="Carte fidélité boulangerie")
    path = build_target_path(result, config)
    assert path.name == "2025-10_Autre_carte-fidelite-boulangerie.pdf"


def test_naming_no_bad_separators(tmp_path):
    """Stem must never start with _, contain __, or end with _ (before suffix)."""
    cases = [
        make_result(document_date=None, correspondent="Unknown", title="Test"),
        make_result(document_date="2025-01-01", correspondent="Unknown", title="Test"),
        make_result(document_date=None, correspondent="EDF", title="Test"),
        make_result(document_date="2025-01-01", correspondent="", title=""),
    ]
    config = make_config("fr", tmp_path)
    for result in cases:
        path = build_target_path(result, config)
        stem = path.stem
        assert not stem.startswith("_"), f"stem starts with _: {stem}"
        assert "__" not in stem, f"stem contains __: {stem}"
        assert not stem.endswith("_"), f"stem ends with _: {stem}"


def test_build_target_path_creates_dir(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result()
    path = build_target_path(result, config)
    assert path.parent.exists()


def test_collision_suffix(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result()
    path1 = build_target_path(result, config)
    path1.parent.mkdir(parents=True, exist_ok=True)
    path1.touch()

    path2 = build_target_path(result, config)
    assert path2 != path1
    assert "_2" in path2.stem


def test_collision_suffix_increments(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result()
    path1 = build_target_path(result, config)
    path1.parent.mkdir(parents=True, exist_ok=True)
    path1.touch()

    path2 = build_target_path(result, config)
    path2.touch()

    path3 = build_target_path(result, config)
    assert "_3" in path3.stem


def test_correspondent_slugified_in_path(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result(correspondent="Crédit Agricole")
    path = build_target_path(result, config)
    assert "cr-dit-agricole" in path.name or "credit-agricole" in path.name


def test_target_is_pdf(tmp_path):
    config = make_config("fr", tmp_path)
    result = make_result()
    path = build_target_path(result, config)
    assert path.suffix == ".pdf"
