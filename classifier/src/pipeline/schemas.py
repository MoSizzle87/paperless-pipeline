"""Schémas Pydantic pour la classification LLM et les entités Paperless-ngx."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentTypeName = Literal[
    "Titre d'identité",
    "Acte d'état civil",
    "Jugement / Acte juridique",
    "Diplôme",
    "Bulletin de paie",
    "Document fiscal",
    "Document Pôle Emploi / France Travail",
    "Document employeur",
    "Relevé bancaire",
    "Mutuelle / Remboursement santé",
    "Ordonnance",
    "Document médical",
    "Assurance",
    "Contrat",
    "Quittance de loyer",
    "Document immobilier",
    "Carte grise / Document véhicule",
    "Facture",
    "Devis / Bon de commande",
    "Bulletin scolaire",
    "Document scolaire",
    "Courrier administratif",
    "Autre",
]


class LLMClassification(BaseModel):
    """Sortie structurée attendue de Claude via tool use."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=120)
    created: date | None
    correspondent: str = Field(min_length=1, max_length=100)
    document_type: DocumentTypeName
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
    """Document Paperless-ngx tel que renvoyé par l'API."""

    id: int
    title: str
    content: str | None = None
    created: str | None = None
    tags: list[int] = Field(default_factory=list)
    correspondent: int | None = None
    document_type: int | None = None


class ClassificationResult(BaseModel):
    """Résultat d'un traitement complet d'un document, pour le logging."""

    doc_id: int
    status: Literal["ok", "review", "failed"]
    confidence: float | None = None
    document_type: str | None = None
    correspondent: str | None = None
    correspondent_created: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read: int | None = None  # ← nouveau
    cache_write: int | None = None  # ← nouveau
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None
