from __future__ import annotations

import csv
import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

_DOCUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    hash_sha256 TEXT,
    source_filename TEXT,
    source_size_bytes INTEGER,
    processed_at TEXT,
    status TEXT,
    document_type TEXT,
    correspondent TEXT,
    document_date TEXT,
    title TEXT,
    target_path TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    confidence REAL,
    language TEXT,
    new_correspondent INTEGER,
    error_stage TEXT,
    error_message TEXT,
    ocr_skipped INTEGER,
    processing_duration_seconds REAL
)
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
USING fts5(id UNINDEXED, ocr_text, tokenize='unicode61')
"""


def init_db(path: Path) -> None:
    """Create the SQLite database and tables if they don't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(_DOCUMENTS_DDL)
        conn.execute(_FTS_DDL)
        conn.commit()


@contextmanager
def open_db(path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager: opens a SQLite connection, commits on success, rolls back on error."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _coerce_row(row: dict) -> dict:
    """Normalise types from journal CSV strings to SQLite-compatible values."""
    out = dict(row)
    for key in ("new_correspondent", "ocr_skipped"):
        val = out.get(key, "")
        if isinstance(val, bool):
            out[key] = int(val)
        else:
            out[key] = 1 if str(val).lower() in ("true", "1", "yes") else 0
    for key in ("confidence", "processing_duration_seconds"):
        try:
            out[key] = float(out.get(key) or 0)
        except (ValueError, TypeError):
            out[key] = 0.0
    for key in ("source_size_bytes",):
        try:
            out[key] = int(out.get(key) or 0)
        except (ValueError, TypeError):
            out[key] = 0
    return out


def index_document(
    conn: sqlite3.Connection,
    journal_row: dict,
    ocr_text: str,
) -> None:
    """Insert or replace a document in the index (documents table + FTS5 table)."""
    row = _coerce_row(journal_row)
    conn.execute(
        """
        INSERT OR REPLACE INTO documents
        (id, hash_sha256, source_filename, source_size_bytes, processed_at,
         status, document_type, correspondent, document_date, title, target_path,
         llm_provider, llm_model, confidence, language, new_correspondent,
         error_stage, error_message, ocr_skipped, processing_duration_seconds)
        VALUES
        (:id, :hash_sha256, :source_filename, :source_size_bytes, :processed_at,
         :status, :document_type, :correspondent, :document_date, :title, :target_path,
         :llm_provider, :llm_model, :confidence, :language, :new_correspondent,
         :error_stage, :error_message, :ocr_skipped, :processing_duration_seconds)
        """,
        row,
    )
    # FTS5 upsert: delete by id (full scan at this scale), then insert fresh entry
    conn.execute("DELETE FROM documents_fts WHERE id = ?", (row["id"],))
    conn.execute(
        "INSERT INTO documents_fts(id, ocr_text) VALUES (?, ?)",
        (row["id"], ocr_text or ""),
    )


def search(
    conn: sqlite3.Connection,
    query: str,
    filters: dict | None = None,
) -> list[dict]:
    """
    Search documents by FTS5 query and/or metadata filters.
    Returns dicts matching all specified criteria, sorted newest first.
    """
    filters = filters or {}
    params: list[Any] = []
    conditions: list[str] = []

    if query and query.strip():
        conditions.append(
            "d.id IN (SELECT id FROM documents_fts WHERE documents_fts MATCH ?)"
        )
        params.append(query.strip())

    if filters.get("document_type"):
        conditions.append("d.document_type = ?")
        params.append(filters["document_type"])

    if filters.get("correspondent"):
        conditions.append("d.correspondent LIKE ?")
        params.append(f"%{filters['correspondent']}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT d.* FROM documents d {where} ORDER BY d.processed_at DESC"

    try:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        logger.warning("FTS search query failed, returning empty", extra={"query": query})
        return []


def _read_pdf_text(path: Path) -> str:
    """Extract all text from a PDF without page or character truncation."""
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        parts = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(parts)
        text = re.sub(r"[ \t]{3,}", "  ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as exc:
        logger.warning(
            "Could not extract PDF text for indexing",
            extra={"path": str(path), "error": str(exc)},
        )
        return ""


def rebuild(
    conn: sqlite3.Connection,
    library_path: Path,
    journal_path: Path,
) -> int:
    """
    Rebuild the index from scratch using journal.csv and OCR text from the library.
    Clears both tables then re-indexes every journal entry.
    Returns the count of successfully indexed documents.
    """
    conn.execute("DELETE FROM documents")
    conn.execute("DELETE FROM documents_fts")

    if not journal_path.exists():
        return 0

    with open(journal_path, newline="") as f:
        rows = list(csv.DictReader(f))

    count = 0
    for row in rows:
        ocr_text = ""
        target = row.get("target_path", "")
        if target:
            p = Path(target)
            if p.exists() and p.suffix.lower() == ".pdf":
                ocr_text = _read_pdf_text(p)
        try:
            index_document(conn, row, ocr_text)
            count += 1
        except Exception as exc:
            logger.warning(
                "Could not index document during rebuild",
                extra={"id": row.get("id"), "error": str(exc)},
            )

    return count
