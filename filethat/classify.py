from __future__ import annotations

import json
import logging
from typing import Literal, Protocol

import tenacity
from pydantic import BaseModel

from filethat.config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a document classifier for administrative documents. Given the OCR'd text of a document, \
classify it by filling the provided tool schema.

Rules:
- `document_type` must be one of the provided keys. Use "other" only as last resort.
- `correspondent` is the issuing organization (e.g., "EDF", "DGFiP", a doctor's name, an employer). \
Prefer values from the provided list. If the correspondent is clearly identified but not in the list, \
use its name and set `new_correspondent: true`. If unidentifiable, use "Unknown".
- `document_date` is the document's issue/reference date, NOT today. ISO format. Null if absent.
- `title` is a short, meaningful descriptor (e.g., "Relevé octobre 2025", "Avis taxe habitation 2024"). \
No filler words.
- `confidence` is your honest self-assessment. Below 0.7 = uncertain.
- Respond ONLY via the tool call."""

ANTHROPIC_TOOL = {
    "name": "classify_document",
    "description": "Classify an administrative document",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {"type": "string", "description": "Document type key"},
            "correspondent": {"type": "string", "description": "Issuing organization"},
            "document_date": {
                "type": ["string", "null"],
                "description": "ISO date YYYY-MM-DD or null",
            },
            "title": {"type": "string", "description": "Short descriptive title, 3-8 words"},
            "language": {
                "type": "string",
                "enum": ["fr", "en", "other"],
                "description": "Document language",
            },
            "confidence": {
                "type": "number",
                "description": "Self-assessed confidence 0.0-1.0",
            },
            "reasoning": {
                "type": "string",
                "description": "1-2 sentences of reasoning",
            },
            "new_correspondent": {
                "type": "boolean",
                "description": "True if correspondent not in the provided list",
            },
        },
        "required": [
            "document_type",
            "correspondent",
            "document_date",
            "title",
            "language",
            "confidence",
            "reasoning",
            "new_correspondent",
        ],
    },
}

OPENAI_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_document",
        "description": "Classify an administrative document",
        "parameters": {
            "type": "object",
            "properties": {
                "document_type": {"type": "string"},
                "correspondent": {"type": "string"},
                "document_date": {"type": ["string", "null"]},
                "title": {"type": "string"},
                "language": {"type": "string", "enum": ["fr", "en", "other"]},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
                "new_correspondent": {"type": "boolean"},
            },
            "required": [
                "document_type",
                "correspondent",
                "document_date",
                "title",
                "language",
                "confidence",
                "reasoning",
                "new_correspondent",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


class ClassificationResult(BaseModel):
    document_type: str
    correspondent: str
    document_date: str | None
    title: str
    language: Literal["fr", "en", "other"]
    confidence: float
    reasoning: str
    new_correspondent: bool


class Classifier(Protocol):
    def classify(self, text: str, config: Config) -> ClassificationResult: ...


def _is_transient(exc: Exception) -> bool:
    try:
        import anthropic

        if isinstance(
            exc,
            (
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ),
        ):
            return True
    except ImportError:
        pass

    try:
        import openai

        if isinstance(
            exc,
            (
                openai.APIConnectionError,
                openai.RateLimitError,
                openai.InternalServerError,
            ),
        ):
            return True
    except ImportError:
        pass

    return False


def _build_user_prompt(text: str, config: Config) -> str:
    types = ", ".join(dt.key for dt in config.referential.document_types)
    correspondents = ", ".join(config.referential.correspondents[:30])
    return (
        f"Document types available: {types}\n"
        f"Known correspondents: {correspondents}\n\n"
        f"Document text:\n{text}"
    )


class AnthropicClassifier:
    def classify(self, text: str, config: Config) -> ClassificationResult:
        import anthropic

        client = anthropic.Anthropic()

        if config.llm.prompt_caching:
            system: str | list[dict] = [
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ]
            tool: dict = {**ANTHROPIC_TOOL, "cache_control": {"type": "ephemeral"}}
        else:
            system = SYSTEM_PROMPT
            tool = ANTHROPIC_TOOL

        @tenacity.retry(
            retry=tenacity.retry_if_exception(_is_transient),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
            stop=tenacity.stop_after_attempt(3),
            reraise=True,
        )
        def _call() -> ClassificationResult:
            response = client.messages.create(
                model=config.llm.model,
                max_tokens=1024,
                temperature=config.llm.temperature,
                system=system,
                messages=[{"role": "user", "content": _build_user_prompt(text, config)}],
                tools=[tool],
                tool_choice={"type": "tool", "name": "classify_document"},
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "classify_document":
                    return ClassificationResult.model_validate(block.input)
            raise ValueError("No classify_document tool_use block in response")

        return _call()


class OpenAIClassifier:
    def classify(self, text: str, config: Config) -> ClassificationResult:
        import openai

        client = openai.OpenAI()

        @tenacity.retry(
            retry=tenacity.retry_if_exception(_is_transient),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
            stop=tenacity.stop_after_attempt(3),
            reraise=True,
        )
        def _call() -> ClassificationResult:
            response = client.chat.completions.create(
                model=config.llm.model,
                temperature=config.llm.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(text, config)},
                ],
                tools=[OPENAI_TOOL],
                tool_choice={"type": "function", "function": {"name": "classify_document"}},
            )
            call = response.choices[0].message.tool_calls[0]
            data = json.loads(call.function.arguments)
            return ClassificationResult.model_validate(data)

        return _call()


def get_classifier(config: Config) -> Classifier:
    if config.llm.provider == "anthropic":
        return AnthropicClassifier()
    if config.llm.provider == "openai":
        return OpenAIClassifier()
    raise ValueError(f"Unknown LLM provider: {config.llm.provider!r}")
