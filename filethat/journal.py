from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

HEADERS = [
    "id",
    "hash_sha256",
    "source_filename",
    "source_size_bytes",
    "processed_at",
    "status",
    "document_type",
    "correspondent",
    "document_date",
    "title",
    "target_path",
    "llm_provider",
    "llm_model",
    "confidence",
    "language",
    "new_correspondent",
    "error_stage",
    "error_message",
    "ocr_skipped",
    "processing_duration_seconds",
]


@dataclass
class JournalEntry:
    id: str
    hash_sha256: str
    source_filename: str
    source_size_bytes: int
    processed_at: str
    status: str
    document_type: str = ""
    correspondent: str = ""
    document_date: str = ""
    title: str = ""
    target_path: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    confidence: float = 0.0
    language: str = ""
    new_correspondent: bool = False
    error_stage: str = ""
    error_message: str = ""
    ocr_skipped: bool = False
    processing_duration_seconds: float = 0.0


class Journal:
    def __init__(self, path: Path, db_path: Path | None = None) -> None:
        self.path = path
        self.db_path = db_path
        self._hashes: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._hashes.add(row["hash_sha256"])

    def has_hash(self, sha256: str) -> bool:
        return sha256 in self._hashes

    def append(self, entry: JournalEntry, ocr_text: str = "") -> None:
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            if needs_header:
                writer.writeheader()
            writer.writerow(asdict(entry))
            f.flush()
        self._hashes.add(entry.hash_sha256)
        if self.db_path is not None:
            self._index(entry, ocr_text)

    def _index(self, entry: JournalEntry, ocr_text: str) -> None:
        try:
            from filethat.index import _read_pdf_text, index_document, init_db, open_db

            text = ocr_text
            if not text and entry.target_path:
                target = Path(entry.target_path)
                if target.exists() and target.suffix.lower() == ".pdf":
                    text = _read_pdf_text(target)

            init_db(self.db_path)  # type: ignore[arg-type]
            with open_db(self.db_path) as conn:  # type: ignore[arg-type]
                index_document(conn, asdict(entry), text)
        except Exception as exc:
            logger.warning(
                "SQLite indexing failed; CSV remains the source of truth",
                extra={"id": entry.id, "error": str(exc)},
            )

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())[:8]
