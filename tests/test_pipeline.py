from __future__ import annotations

import csv
import fcntl
import json
from unittest.mock import MagicMock, patch

import pytest

from filethat.classify import ClassificationResult
from filethat.cli import _scan_lock
from filethat.config import Config
from filethat.journal import Journal
from filethat.pipeline import process_file


def test_concurrent_scan_exits_with_code_1(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    lock_path = data_dir / ".filethat.lock"

    with open(lock_path, "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(SystemExit) as exc_info:
            with _scan_lock(data_dir):
                pass

        assert exc_info.value.code == 1


# --- Review routing helpers ---

def _make_config(tmp_path, confidence_threshold=0.7, review_enabled=True):
    config = Config.model_validate({
        "llm": {"provider": "anthropic"},
        "paths": {
            "inbox": str(tmp_path / "inbox"),
            "library": str(tmp_path / "library"),
            "failed": str(tmp_path / "failed"),
            "archive": str(tmp_path / "archive"),
            "review": str(tmp_path / "review"),
            "journal": str(tmp_path / "journal.csv"),
        },
        "review": {
            "enabled": review_enabled,
            "confidence_threshold": confidence_threshold,
        },
        "referential": {
            "document_types": [{"key": "invoice", "fr": "Facture", "en": "Invoice"}],
            "correspondents": [],
        },
    })
    for d in [config.paths.inbox, config.paths.library, config.paths.failed,
              config.paths.archive, config.paths.review]:
        d.mkdir(parents=True, exist_ok=True)
    return config


def _make_result(confidence=0.9):
    return ClassificationResult(
        document_type="invoice",
        correspondent="EDF",
        document_date="2024-01-15",
        title="Test document",
        language="fr",
        confidence=confidence,
        reasoning="Test",
        new_correspondent=False,
    )


def _run_pipeline(tmp_path, source, config, confidence):
    ocr_file = tmp_path / "ocr.pdf"
    ocr_file.write_bytes(b"%PDF-1.4 ocr")
    journal = Journal(config.paths.journal)
    with patch("filethat.pipeline.normalize", return_value=(ocr_file, False)), \
         patch("filethat.pipeline.extract_text", return_value="sample text"), \
         patch("filethat.pipeline.get_classifier") as mock_gc:
        mock_gc.return_value.classify.return_value = _make_result(confidence=confidence)
        process_file(source, config, journal)
    return journal


# --- Review routing tests ---

def test_low_confidence_routes_to_review(tmp_path):
    config = _make_config(tmp_path, confidence_threshold=0.7)
    source = config.paths.inbox / "test.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    _run_pipeline(tmp_path, source, config, confidence=0.5)

    assert len(list(config.paths.review.glob("*.pdf"))) == 1
    assert len(list(config.paths.library.rglob("*.pdf"))) == 0


def test_high_confidence_routes_to_library(tmp_path):
    config = _make_config(tmp_path, confidence_threshold=0.7)
    source = config.paths.inbox / "test.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    _run_pipeline(tmp_path, source, config, confidence=0.9)

    assert len(list(config.paths.library.rglob("*.pdf"))) == 1
    assert len(list(config.paths.review.glob("*.pdf"))) == 0


def test_review_suggestion_json_written(tmp_path):
    config = _make_config(tmp_path)
    source = config.paths.inbox / "test.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    _run_pipeline(tmp_path, source, config, confidence=0.4)

    suggestion_files = list(config.paths.review.glob("*.suggestion.json"))
    assert len(suggestion_files) == 1
    data = json.loads(suggestion_files[0].read_text())
    assert data["document_type"] == "invoice"
    assert data["confidence"] == 0.4
    assert data["correspondent"] == "EDF"
    assert data["title"] == "Test document"


def test_review_journal_status(tmp_path):
    config = _make_config(tmp_path)
    source = config.paths.inbox / "test.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    _run_pipeline(tmp_path, source, config, confidence=0.3)

    with open(config.paths.journal, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "review"
    assert "review" in rows[0]["target_path"]


def test_review_disabled_routes_high_conf_to_library(tmp_path):
    config = _make_config(tmp_path, review_enabled=False)
    source = config.paths.inbox / "test.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    _run_pipeline(tmp_path, source, config, confidence=0.3)

    assert len(list(config.paths.library.rglob("*.pdf"))) == 1
    assert len(list(config.paths.review.glob("*.pdf"))) == 0
