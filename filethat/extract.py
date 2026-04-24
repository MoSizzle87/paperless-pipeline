from __future__ import annotations

import logging
import re
from pathlib import Path

import pypdf

from filethat.config import Config

logger = logging.getLogger(__name__)


def extract_text(pdf_path: Path, config: Config) -> str:
    """Extract text from first N pages, truncated to max_chars."""
    reader = pypdf.PdfReader(str(pdf_path))
    pages = reader.pages[: config.llm.max_pages]

    parts: list[str] = []
    for page in pages:
        text = page.extract_text() or ""
        parts.append(text)

    combined = "\n".join(parts)
    combined = re.sub(r"[ \t]{3,}", "  ", combined)
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    combined = combined.strip()

    return combined[: config.llm.max_chars]
