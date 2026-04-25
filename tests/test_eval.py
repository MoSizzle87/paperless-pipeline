from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from filethat.classify import ClassificationResult
from filethat.config import Config
from filethat.eval import (
    EvalDocumentResult,
    _Usage,
    _confusion_matrix,
    _ece,
    _field_accuracy,
    run_eval,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    filename: str = "doc.pdf",
    expected: dict | None = None,
    document_type: str = "invoice",
    correspondent: str = "EDF",
    document_date: str = "2025-01-01",
    language: str = "fr",
    confidence: float = 0.9,
    predicted: bool = True,
    error: str | None = None,
) -> EvalDocumentResult:
    pred = (
        ClassificationResult(
            document_type=document_type,
            correspondent=correspondent,
            document_date=document_date,
            title="Test",
            language=language,  # type: ignore[arg-type]
            confidence=confidence,
            reasoning="ok",
            new_correspondent=False,
        )
        if predicted
        else None
    )
    return EvalDocumentResult(
        filename=filename,
        expected=expected
        or {
            "document_type": document_type,
            "correspondent": correspondent,
            "document_date": document_date,
            "language": language,
        },
        predicted=pred,
        error=error,
        duration_total=1.0,
        duration_ocr=0.5,
        duration_llm=0.4,
        usage=_Usage(input_tokens=100, output_tokens=50, cost_usd=0.001),
    )


def _make_config(tmp_path: Path) -> Config:
    return Config.model_validate(
        {
            "llm": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "paths": {
                "inbox": str(tmp_path / "inbox"),
                "library": str(tmp_path / "library"),
                "failed": str(tmp_path / "failed"),
                "archive": str(tmp_path / "archive"),
                "review": str(tmp_path / "review"),
                "journal": str(tmp_path / "journal.csv"),
            },
            "referential": {
                "document_types": [{"key": "invoice", "fr": "Facture", "en": "Invoice"}],
                "correspondents": ["EDF"],
            },
        }
    )


# ---------------------------------------------------------------------------
# _field_accuracy
# ---------------------------------------------------------------------------


def test_field_accuracy_all_correct():
    results = [_result(document_type="invoice") for _ in range(3)]
    c, t = _field_accuracy(results, "document_type")
    assert c == 3 and t == 3


def test_field_accuracy_partial():
    results = [
        _result(document_type="invoice"),
        _result(document_type="invoice"),
        _result(document_type="banking", expected={"document_type": "invoice"}),
    ]
    c, t = _field_accuracy(results, "document_type")
    assert c == 2 and t == 3


def test_field_accuracy_field_absent_in_expected():
    results = [
        _result(expected={"document_type": "invoice"}),  # no document_date
        _result(),  # has document_date
    ]
    c, t = _field_accuracy(results, "document_date")
    assert t == 1


def test_field_accuracy_failed_prediction_excluded():
    results = [_result(predicted=False, error="boom")]
    c, t = _field_accuracy(results, "document_type")
    assert c == 0 and t == 0


def test_field_accuracy_case_insensitive():
    results = [_result(correspondent="edf", expected={"correspondent": "EDF"})]
    c, t = _field_accuracy(results, "correspondent")
    assert c == 1 and t == 1


# ---------------------------------------------------------------------------
# _ece
# ---------------------------------------------------------------------------


def test_ece_perfect_calibration():
    results = [_result(confidence=1.0, document_type="invoice") for _ in range(5)]
    assert _ece(results) == 0.0


def test_ece_complete_miscalibration():
    results = [
        _result(
            confidence=1.0,
            document_type="banking",
            expected={"document_type": "invoice"},
        )
        for _ in range(5)
    ]
    # conf=1.0 → last bin; acc=0.0, avg_conf=1.0 → ECE = 1.0
    assert _ece(results) == 1.0


def test_ece_empty_returns_zero():
    assert _ece([]) == 0.0


def test_ece_no_document_type_in_expected():
    results = [_result(expected={"correspondent": "EDF"})]
    assert _ece(results) == 0.0


def test_ece_known_value():
    # 3 items in same bin: conf=0.9, 2 correct, 1 wrong → acc=2/3
    results = [
        _result(confidence=0.9, document_type="invoice"),
        _result(confidence=0.9, document_type="invoice"),
        _result(confidence=0.9, document_type="banking", expected={"document_type": "invoice"}),
    ]
    # ECE = |0.9 - 2/3| = 0.2333...
    assert abs(_ece(results) - round(abs(0.9 - 2 / 3), 4)) < 1e-4


# ---------------------------------------------------------------------------
# _confusion_matrix
# ---------------------------------------------------------------------------


def test_confusion_matrix_structure():
    results = [
        _result(document_type="invoice"),
        _result(document_type="invoice"),
        _result(document_type="banking", expected={"document_type": "invoice"}),
    ]
    labels, matrix = _confusion_matrix(results)
    assert "invoice" in labels
    assert "banking" in labels
    assert matrix["invoice"]["invoice"] == 2
    assert matrix["invoice"]["banking"] == 1


def test_confusion_matrix_empty():
    labels, matrix = _confusion_matrix([])
    assert labels == []
    assert matrix == {}


def test_confusion_matrix_excludes_missing_field():
    results = [_result(expected={"correspondent": "EDF"})]
    labels, matrix = _confusion_matrix(results)
    assert labels == []


# ---------------------------------------------------------------------------
# run_eval
# ---------------------------------------------------------------------------


def _make_golden(tmp_path: Path, entries: list[dict]) -> Path:
    dataset = tmp_path / "eval"
    docs = dataset / "documents"
    docs.mkdir(parents=True)
    (dataset / "golden.json").write_text(json.dumps(entries))
    return dataset


def _fake_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def _make_eval_result(
    doc_path: Path, expected: dict, config: object, provider: str
) -> EvalDocumentResult:
    return _result(
        filename=doc_path.name,
        expected=expected,
        document_type=expected["document_type"],
        correspondent=expected.get("correspondent", "Unknown"),
    )


def test_run_eval_writes_report(tmp_path):
    golden_entries = [
        {"filename": "a.pdf", "expected": {"document_type": "invoice", "correspondent": "EDF"}},
        {"filename": "b.pdf", "expected": {"document_type": "tax", "correspondent": "DGFiP"}},
    ]
    dataset = _make_golden(tmp_path, golden_entries)
    _fake_pdf(dataset / "documents" / "a.pdf")
    _fake_pdf(dataset / "documents" / "b.pdf")
    config = _make_config(tmp_path)

    with patch("filethat.eval._eval_document", side_effect=_make_eval_result):
        reports, models = run_eval(dataset, ["anthropic"], config)

    assert "anthropic" in reports
    assert len(reports["anthropic"]) == 2
    report_files = list(dataset.glob("report_*.md"))
    assert len(report_files) == 1
    content = report_files[0].read_text()
    assert "Document type accuracy" in content
    assert "Confidence ECE" in content


def test_run_eval_does_not_touch_journal(tmp_path):
    dataset = _make_golden(tmp_path, [])
    config = _make_config(tmp_path)

    with patch("filethat.eval._eval_document", side_effect=_make_eval_result):
        run_eval(dataset, ["anthropic"], config)

    assert not config.paths.journal.exists()
    assert not config.paths.library.exists()


def test_run_eval_skips_missing_documents(tmp_path):
    golden_entries = [
        {"filename": "missing.pdf", "expected": {"document_type": "invoice", "correspondent": "X"}},
    ]
    dataset = _make_golden(tmp_path, golden_entries)
    config = _make_config(tmp_path)

    with patch("filethat.eval._eval_document", side_effect=_make_eval_result) as mock_eval:
        reports, _ = run_eval(dataset, ["anthropic"], config)

    mock_eval.assert_not_called()
    assert reports["anthropic"] == []


def test_run_eval_comparative_report(tmp_path):
    golden_entries = [
        {"filename": "a.pdf", "expected": {"document_type": "invoice", "correspondent": "EDF"}},
    ]
    dataset = _make_golden(tmp_path, golden_entries)
    _fake_pdf(dataset / "documents" / "a.pdf")
    config = _make_config(tmp_path)

    with patch("filethat.eval._eval_document", side_effect=_make_eval_result):
        reports, models = run_eval(dataset, ["anthropic", "openai"], config)

    assert set(reports) == {"anthropic", "openai"}
    content = list(dataset.glob("report_*.md"))[0].read_text()
    assert "Cross-provider comparison" in content
