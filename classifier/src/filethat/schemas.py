"""Pydantic schemas for LLM classification output and Paperless-ngx entities."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentTypeId = Literal[
    "identity-document",
    "civil-status",
    "legal-document",
    "diploma",
    "payslip",
    "tax-document",
    "unemployment-document",
    "employer-document",
    "bank-statement",
    "health-insurance",
    "prescription",
    "medical-document",
    "insurance",
    "contract",
    "rent-receipt",
    "real-estate",
    "vehicle-document",
    "invoice",
    "quote",
    "school-report",
    "school-document",
    "administrative-letter",
    "other",
]


class LLMClassification(BaseModel):
    """Structured output expected from the LLM via tool use / function calling."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=120)
    created: date | None
    correspondent: str = Field(min_length=1, max_length=100)
    document_type: DocumentTypeId
    tags: list[str] = Field(min_length=2, max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("tags")
    @classmethod
    def tags_lowercase_ascii(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v]


class PaperlessTag(BaseModel):
    id: int
    name: str


class PaperlessCorrespondent(BaseModel):
    id: int
    name: str


class PaperlessDocumentType(BaseModel):
    id: int
    name: str


class PaperlessDocument(BaseModel):
    """Document as returned by the Paperless-ngx REST API."""

    id: int
    title: str
    content: str | None = None
    created: str | None = None
    tags: list[int] = Field(default_factory=list)
    correspondent: int | None = None
    document_type: int | None = None


class ClassificationResult(BaseModel):
    """Full processing result for a single document, used for logging."""

    doc_id: int
    status: Literal["ok", "review", "failed"]
    confidence: float | None = None
    document_type: str | None = None
    correspondent: str | None = None
    correspondent_created: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None
