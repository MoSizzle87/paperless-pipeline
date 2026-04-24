from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class DocumentType(BaseModel):
    key: str
    fr: str
    en: str


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-4-6"
    temperature: float = 0
    max_pages: int = 5
    max_chars: int = 15000


class OCRConfig(BaseModel):
    languages: list[str] = ["fra", "eng"]
    force_reocr: bool = False
    output_type: str = "pdfa"


class PathsConfig(BaseModel):
    inbox: Path = Path("/app/data/inbox")
    library: Path = Path("/app/data/library")
    failed: Path = Path("/app/data/failed")
    archive: Path = Path("/app/data/archive")
    journal: Path = Path("/app/data/journal.csv")


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class ReferentialConfig(BaseModel):
    document_types: list[DocumentType] = []
    correspondents: list[str] = []


class Config(BaseModel):
    language: Literal["fr", "en"] = "fr"
    llm: LLMConfig = LLMConfig()
    ocr: OCRConfig = OCRConfig()
    paths: PathsConfig = PathsConfig()
    web: WebConfig = WebConfig()
    referential: ReferentialConfig = ReferentialConfig()

    @classmethod
    def load(cls, path: Path = Path("config.yaml")) -> Config:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def get_type_label(self, key: str) -> str:
        for dt in self.referential.document_types:
            if dt.key == key:
                return getattr(dt, self.language)
        return key
