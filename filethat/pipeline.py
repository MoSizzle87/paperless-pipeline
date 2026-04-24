from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from filethat.classify import get_classifier
from filethat.config import Config
from filethat.extract import extract_text
from filethat.journal import Journal, JournalEntry
from filethat.normalize import normalize
from filethat.organize import organize

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def process_file(path: Path, config: Config, journal: Journal) -> None:
    if not path.exists():
        logger.warning("File disappeared before processing, skipping", extra={"file": str(path)})
        return

    entry_id = Journal.new_id()
    start_time = time.monotonic()
    processed_at = datetime.now(timezone.utc).isoformat()
    source_size = path.stat().st_size

    logger.info("Processing file", extra={"file": str(path), "id": entry_id})

    file_hash = _sha256(path)
    if journal.has_hash(file_hash):
        logger.info("Skipping duplicate", extra={"hash": file_hash, "file": str(path)})
        return

    error_stage = ""
    ocr_pdf: Path | None = None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            error_stage = "normalize"
            ocr_pdf, ocr_skipped = normalize(path, config, tmp_dir)

            error_stage = "extract"
            text = extract_text(ocr_pdf, config)

            error_stage = "classify"
            classifier = get_classifier(config)
            result = classifier.classify(text, config)

            error_stage = "organize"
            target = organize(ocr_pdf, result, config)
            ocr_pdf = None  # moved; don't preserve on error

            error_stage = "journal"
            duration = time.monotonic() - start_time
            journal.append(
                JournalEntry(
                    id=entry_id,
                    hash_sha256=file_hash,
                    source_filename=path.name,
                    source_size_bytes=source_size,
                    processed_at=processed_at,
                    status="success",
                    document_type=result.document_type,
                    correspondent=result.correspondent,
                    document_date=result.document_date or "",
                    title=result.title,
                    target_path=str(target),
                    llm_provider=config.llm.provider,
                    llm_model=config.llm.model,
                    confidence=result.confidence,
                    language=result.language,
                    new_correspondent=result.new_correspondent,
                    ocr_skipped=ocr_skipped,
                    processing_duration_seconds=round(duration, 2),
                )
            )

            path.unlink()
            logger.info(
                "Processed successfully",
                extra={"id": entry_id, "target": str(target)},
            )

        except Exception as exc:
            duration = time.monotonic() - start_time
            tb = traceback.format_exc()
            logger.error(
                "Pipeline error",
                extra={"id": entry_id, "stage": error_stage, "error": str(exc)},
            )

            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            failed_dir = config.paths.failed / f"{entry_id}_{ts}"
            failed_dir.mkdir(parents=True, exist_ok=True)

            try:
                shutil.copy2(str(path), str(failed_dir / path.name))
            except Exception:
                logger.warning(
                    "Could not copy source to failed dir",
                    extra={"source": str(path)},
                )

            if ocr_pdf and ocr_pdf.exists():
                try:
                    shutil.copy2(str(ocr_pdf), str(failed_dir / ocr_pdf.name))
                except Exception:
                    pass

            error_info = {
                "id": entry_id,
                "stage": error_stage,
                "error": str(exc),
                "traceback": tb,
            }
            (failed_dir / "error.json").write_text(json.dumps(error_info, indent=2))

            journal.append(
                JournalEntry(
                    id=entry_id,
                    hash_sha256=file_hash,
                    source_filename=path.name,
                    source_size_bytes=source_size,
                    processed_at=processed_at,
                    status="error",
                    error_stage=error_stage,
                    error_message=str(exc)[:500],
                    processing_duration_seconds=round(duration, 2),
                    llm_provider=config.llm.provider,
                    llm_model=config.llm.model,
                )
            )

            try:
                path.unlink()
            except Exception:
                pass
