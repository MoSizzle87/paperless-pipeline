"""Configuration du logging : console pour debug + JSONL rotatif pour audit."""

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter

from pipeline.schemas import ClassificationResult


def setup_logging(log_level: str, log_dir: Path) -> None:
    """Configure les loggers racine (console) et 'pipeline.audit' (JSONL rotatif)."""
    log_dir.mkdir(parents=True, exist_ok=True)

    # Logger racine : stdout lisible humain
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

    # Logger 'pipeline.audit' : JSONL par-doc, rotation par taille
    audit = logging.getLogger("pipeline.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = False  # pas de doublon sur la console

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
    """Émet une ligne JSONL d'audit pour un document traité."""
    audit = logging.getLogger("pipeline.audit")
    audit.info(
        "doc_classified",
        extra={
            "ts": datetime.now(timezone.utc).isoformat(),
            **result.model_dump(exclude_none=True),
        },
    )
