"""Logging configuration: human-readable console output + rotating JSONL audit log."""

import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter

from filethat.schemas import ClassificationResult


def setup_logging(log_level: str, log_dir: Path) -> None:
    """Configure root logger (console) and 'filethat.audit' logger (rotating JSONL)."""
    log_dir.mkdir(parents=True, exist_ok=True)

    # Root logger: human-readable stdout
    root = logging.getLogger()
    root.setLevel(log_level.upper())
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(console)

    # 'filethat.audit' logger: per-document JSONL, size-based rotation
    audit = logging.getLogger("filethat.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = False  # no duplicate output on console
    audit_file = log_dir / "pipeline.jsonl"
    handler = RotatingFileHandler(
        audit_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,  # 5 rotations → ~50 MB max
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter("%(ts)s %(message)s", rename_fields={"message": "event"}))
    audit.addHandler(handler)


def log_classification(result: ClassificationResult) -> None:
    """Emit a JSONL audit line for a processed document."""
    audit = logging.getLogger("filethat.audit")
    audit.info(
        "doc_classified",
        extra={
            "ts": datetime.now(UTC).isoformat(),
            **result.model_dump(exclude_none=True),
        },
    )
