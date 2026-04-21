"""System prompt loading and classify tool definition for document classification."""

from pathlib import Path
from typing import get_args

from filethat.schemas import DocumentTypeId

# Stable document type ids — must match document_types.yaml
DOCUMENT_TYPE_ENUM: list[str] = list(get_args(DocumentTypeId))

# Prompts directory
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_system_prompt(language: str = "fr") -> str:
    """Load the system prompt for the given language.

    Falls back to English if the requested language is not available.
    """
    prompt_file = _PROMPTS_DIR / f"system_{language}.md"
    if not prompt_file.exists():
        fallback = _PROMPTS_DIR / "system_en.md"
        if not fallback.exists():
            raise FileNotFoundError(
                f"No system prompt found for language '{language}' "
                f"and fallback 'en' is also missing."
            )
        return fallback.read_text(encoding="utf-8")
    return prompt_file.read_text(encoding="utf-8")


# Default prompt loaded at import time for backward compatibility
SYSTEM_PROMPT = load_system_prompt("fr")


def build_user_message(ocr_text: str) -> str:
    """Build the user message containing the OCR text to classify."""
    max_chars = 15_000  # ~4000 tokens
    if len(ocr_text) > max_chars:
        head = ocr_text[: max_chars // 2]
        tail = ocr_text[-max_chars // 2 :]
        ocr_text = f"{head}\n\n[... middle truncated ...]\n\n{tail}"
    return f"<document_ocr>\n{ocr_text}\n</document_ocr>"


CLASSIFY_TOOL = {
    "name": "classify_document",
    "description": (
        "Extract structured metadata from an administrative document. "
        "Call this tool exactly once per document with the classification results."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "Concise title following the pattern "
                    "'[Type] [Correspondent] [readable period]'. "
                    "Example: 'Facture EDF janvier 2019'."
                ),
                "minLength": 3,
                "maxLength": 120,
            },
            "created": {
                "type": ["string", "null"],
                "description": (
                    "Document date in ISO format YYYY-MM-DD. Use null if no date can be identified."
                ),
                "pattern": r"^\d{4}-\d{2}-\d{2}$",
            },
            "correspondent": {
                "type": "string",
                "description": (
                    "Issuing organization. Prefer official acronyms (EDF, CAF, RIVP...). "
                    "Use 'Inconnu' with low confidence if unidentifiable. "
                    "Never use the recipient as correspondent."
                ),
                "minLength": 1,
                "maxLength": 100,
            },
            "document_type": {
                "type": "string",
                "enum": DOCUMENT_TYPE_ENUM,
                "description": (
                    "Exactly one stable id from the allowed values. "
                    "When multiple categories apply, use the lowest-priority match."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
                "description": (
                    "2 to 5 tag ids, lowercase ASCII. "
                    "Prefer standard ids listed in the system prompt."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Calibrated confidence per the <confidence> rules.",
            },
        },
        "required": ["title", "created", "correspondent", "document_type", "tags", "confidence"],
    },
}
