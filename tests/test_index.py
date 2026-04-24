from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from filethat.index import (
    _read_pdf_text,
    index_document,
    init_db,
    open_db,
    rebuild,
    search,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    doc_id: str = "abc00001",
    status: str = "success",
    document_type: str = "invoice",
    correspondent: str = "EDF",
    title: str = "Test invoice",
    target_path: str = "",
) -> dict:
    return {
        "id": doc_id,
        "hash_sha256": "deadbeef" + doc_id,
        "source_filename": "test.pdf",
        "source_size_bytes": 1234,
        "processed_at": "2024-06-01T12:00:00+00:00",
        "status": status,
        "document_type": document_type,
        "correspondent": correspondent,
        "document_date": "2024-06-01",
        "title": title,
        "target_path": target_path,
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-6",
        "confidence": "0.95",
        "language": "fr",
        "new_correspondent": "False",
        "error_stage": "",
        "error_message": "",
        "ocr_skipped": "False",
        "processing_duration_seconds": "7.5",
    }


def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "filethat.db"
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def test_init_db_creates_file(tmp_path):
    db_path = tmp_path / "sub" / "filethat.db"
    init_db(db_path)
    assert db_path.exists()


def test_init_db_creates_documents_table(tmp_path):
    db_path = _db(tmp_path)
    with sqlite3.connect(str(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "documents" in tables


def test_init_db_creates_fts_table(tmp_path):
    db_path = _db(tmp_path)
    with sqlite3.connect(str(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "documents_fts" in tables


def test_init_db_idempotent(tmp_path):
    db_path = _db(tmp_path)
    # Calling twice should not raise
    init_db(db_path)


# ---------------------------------------------------------------------------
# index_document
# ---------------------------------------------------------------------------


def test_index_document_inserts_to_documents(tmp_path):
    db_path = _db(tmp_path)
    row = _make_row()
    with open_db(db_path) as conn:
        index_document(conn, row, "some ocr text")

    with open_db(db_path) as conn:
        result = conn.execute("SELECT id, title FROM documents WHERE id = ?", ("abc00001",)).fetchone()
    assert result is not None
    assert result["title"] == "Test invoice"


def test_index_document_inserts_to_fts(tmp_path):
    db_path = _db(tmp_path)
    with open_db(db_path) as conn:
        index_document(conn, _make_row(), "hello unique keyword")

    with open_db(db_path) as conn:
        hits = conn.execute(
            "SELECT id FROM documents_fts WHERE documents_fts MATCH 'unique'",
        ).fetchall()
    assert any(h["id"] == "abc00001" for h in hits)


def test_index_document_replaces_existing(tmp_path):
    db_path = _db(tmp_path)
    row = _make_row(title="Original title")
    with open_db(db_path) as conn:
        index_document(conn, row, "old text")

    row["title"] = "Updated title"
    with open_db(db_path) as conn:
        index_document(conn, row, "new text")

    with open_db(db_path) as conn:
        results = conn.execute("SELECT id FROM documents WHERE id = 'abc00001'").fetchall()
        fts_results = conn.execute(
            "SELECT id FROM documents_fts WHERE documents_fts MATCH 'new'"
        ).fetchall()
        old_fts = conn.execute(
            "SELECT id FROM documents_fts WHERE documents_fts MATCH 'old'"
        ).fetchall()

    assert len(results) == 1
    assert any(r["id"] == "abc00001" for r in fts_results)
    assert not any(r["id"] == "abc00001" for r in old_fts)


def test_index_document_coerces_bool_strings(tmp_path):
    db_path = _db(tmp_path)
    row = _make_row()
    row["new_correspondent"] = "True"
    row["ocr_skipped"] = "False"
    with open_db(db_path) as conn:
        index_document(conn, row, "")

    with open_db(db_path) as conn:
        r = conn.execute(
            "SELECT new_correspondent, ocr_skipped FROM documents WHERE id = ?", ("abc00001",)
        ).fetchone()
    assert r["new_correspondent"] == 1
    assert r["ocr_skipped"] == 0


def test_index_document_coerces_python_bool(tmp_path):
    db_path = _db(tmp_path)
    row = _make_row()
    row["new_correspondent"] = True
    row["ocr_skipped"] = False
    with open_db(db_path) as conn:
        index_document(conn, row, "")

    with open_db(db_path) as conn:
        r = conn.execute(
            "SELECT new_correspondent FROM documents WHERE id = ?", ("abc00001",)
        ).fetchone()
    assert r["new_correspondent"] == 1


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def _populate(db_path: Path) -> None:
    """Insert three test documents."""
    docs = [
        (_make_row("id000001", document_type="invoice", correspondent="EDF", title="Electricity bill"), "edf electricity releve mensuel"),
        (_make_row("id000002", document_type="tax", correspondent="DGFiP", title="Income tax notice"), "impot revenu avis"),
        (_make_row("id000003", document_type="invoice", correspondent="Orange", title="Phone bill"), "telephone facture mensuelle"),
    ]
    with open_db(db_path) as conn:
        for row, text in docs:
            index_document(conn, row, text)


def test_search_fts_finds_matching_document(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        results = search(conn, "electricity")
    assert len(results) == 1
    assert results[0]["id"] == "id000001"


def test_search_fts_no_results_for_missing_term(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        results = search(conn, "nonexistent_term_xyz")
    assert results == []


def test_search_fts_multiple_results(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        results = search(conn, "mensuel*")
    ids = {r["id"] for r in results}
    assert "id000001" in ids
    assert "id000003" in ids


def test_search_filter_document_type(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        results = search(conn, "", filters={"document_type": "tax"})
    assert len(results) == 1
    assert results[0]["id"] == "id000002"


def test_search_filter_correspondent(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        results = search(conn, "", filters={"correspondent": "Orange"})
    assert len(results) == 1
    assert results[0]["id"] == "id000003"


def test_search_combined_fts_and_filter(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        # Both "mensuel*" docs are invoices; filter by correspondent narrows to one
        results = search(conn, "mensuel*", filters={"document_type": "invoice", "correspondent": "EDF"})
    assert len(results) == 1
    assert results[0]["id"] == "id000001"


def test_search_empty_query_returns_all(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        results = search(conn, "")
    assert len(results) == 3


def test_search_results_ordered_newest_first(tmp_path):
    db_path = _db(tmp_path)
    rows = [
        _make_row("id_old", title="Old doc"),
        _make_row("id_new", title="New doc"),
    ]
    rows[0]["processed_at"] = "2023-01-01T00:00:00+00:00"
    rows[1]["processed_at"] = "2024-01-01T00:00:00+00:00"
    with open_db(db_path) as conn:
        for row in rows:
            index_document(conn, row, "")
    with open_db(db_path) as conn:
        results = search(conn, "")
    assert results[0]["id"] == "id_new"


def test_search_invalid_fts_query_returns_empty(tmp_path):
    db_path = _db(tmp_path)
    _populate(db_path)
    with open_db(db_path) as conn:
        # An unmatched quote is invalid FTS5 syntax
        results = search(conn, '"unclosed phrase')
    assert results == []


# ---------------------------------------------------------------------------
# rebuild
# ---------------------------------------------------------------------------


def _write_journal(journal_path: Path, rows: list[dict]) -> None:
    from filethat.journal import HEADERS

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with open(journal_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            # Fill missing HEADERS columns with empty string
            complete = {k: row.get(k, "") for k in HEADERS}
            writer.writerow(complete)


def test_rebuild_from_journal(tmp_path):
    journal_path = tmp_path / "journal.csv"
    rows = [
        _make_row("r000001", title="Doc one"),
        _make_row("r000002", title="Doc two"),
    ]
    _write_journal(journal_path, rows)

    db_path = _db(tmp_path)
    with open_db(db_path) as conn:
        count = rebuild(conn, tmp_path / "library", journal_path)

    assert count == 2
    with open_db(db_path) as conn:
        all_docs = search(conn, "")
    assert len(all_docs) == 2


def test_rebuild_clears_existing_data(tmp_path):
    journal_path = tmp_path / "journal.csv"
    db_path = _db(tmp_path)

    # Pre-populate with a document not in journal
    with open_db(db_path) as conn:
        index_document(conn, _make_row("stale001"), "stale content")

    # Rebuild with a different document
    _write_journal(journal_path, [_make_row("fresh001", title="Fresh doc")])
    with open_db(db_path) as conn:
        rebuild(conn, tmp_path / "library", journal_path)

    with open_db(db_path) as conn:
        results = search(conn, "")
    ids = {r["id"] for r in results}
    assert "stale001" not in ids
    assert "fresh001" in ids


def test_rebuild_empty_journal(tmp_path):
    journal_path = tmp_path / "journal.csv"
    _write_journal(journal_path, [])
    db_path = _db(tmp_path)
    with open_db(db_path) as conn:
        count = rebuild(conn, tmp_path / "library", journal_path)
    assert count == 0


def test_rebuild_missing_journal(tmp_path):
    db_path = _db(tmp_path)
    with open_db(db_path) as conn:
        count = rebuild(conn, tmp_path / "library", tmp_path / "nonexistent.csv")
    assert count == 0


def test_rebuild_skips_missing_target_files(tmp_path):
    journal_path = tmp_path / "journal.csv"
    row = _make_row("id_notarget", target_path="/nonexistent/path/file.pdf")
    _write_journal(journal_path, [row])

    db_path = _db(tmp_path)
    with open_db(db_path) as conn:
        count = rebuild(conn, tmp_path / "library", journal_path)
    assert count == 1  # indexed with empty OCR text


# ---------------------------------------------------------------------------
# _read_pdf_text
# ---------------------------------------------------------------------------


def test_read_pdf_text_missing_file(tmp_path):
    result = _read_pdf_text(tmp_path / "nonexistent.pdf")
    assert result == ""


def test_read_pdf_text_invalid_file(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    result = _read_pdf_text(bad)
    assert result == ""
