from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

from filethat.classify import ClassificationResult
from filethat.config import Config


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len].rstrip("-")


def build_target_path(
    result: ClassificationResult,
    config: Config,
) -> Path:
    date = result.document_date[:7] if result.document_date else ""

    type_label = config.get_type_label(result.document_type)
    if type_label == result.document_type == "other":
        type_label = "Autre" if config.language == "fr" else "Other"

    raw_correspondent = result.correspondent or ""
    if raw_correspondent.lower() == "unknown":
        raw_correspondent = ""
    correspondent = slugify(raw_correspondent) if raw_correspondent else ""

    title_slug = slugify(result.title) or "document"

    stem = "_".join([s for s in [date, type_label, correspondent, title_slug] if s])

    target_dir = config.paths.library / type_label
    target_dir.mkdir(parents=True, exist_ok=True)

    candidate = target_dir / f"{stem}.pdf"
    if not candidate.exists():
        return candidate

    for i in range(2, 10000):
        candidate = target_dir / f"{stem}_{i}.pdf"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Too many collisions for {stem}")


def organize(ocr_pdf: Path, result: ClassificationResult, config: Config) -> Path:
    target = build_target_path(result, config)
    shutil.move(str(ocr_pdf), str(target))
    return target
