"""Referential management: canonical whitelist (Class A) + auto-creation (Class B)."""

import logging
from pathlib import Path

import yaml

from filethat.normalizer import fuzzy_match, slugify
from filethat.paperless_client import PaperlessClient
from filethat.schemas import PaperlessCorrespondent, PaperlessDocumentType, PaperlessTag

logger = logging.getLogger(__name__)


class DocumentTypeRegistry:
    """Loads document types from YAML and resolves id ↔ label in a given language."""

    def __init__(self, yaml_path: Path, language: str = "fr") -> None:
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._language = language
        self._id_to_label: dict[str, str] = {}
        self._ids: list[str] = []
        for entry in sorted(data, key=lambda e: e.get("priority", 99)):
            doc_id: str = entry["id"]
            label: str = entry["labels"].get(language) or entry["labels"]["fr"]
            self._id_to_label[doc_id] = label
            self._ids.append(doc_id)

    @property
    def ids(self) -> list[str]:
        """All document type ids, ordered by priority."""
        return list(self._ids)

    def label(self, doc_id: str) -> str:
        """Return the display label for a given id in the configured language."""
        if doc_id not in self._id_to_label:
            raise KeyError(f"Unknown document type id: '{doc_id}'")
        return self._id_to_label[doc_id]


class CanonicalCorrespondents:
    """Canonical correspondent whitelist (Class A), loaded from YAML.

    Loads the base file and merges correspondents.local.yaml if present.
    """

    def __init__(self, yaml_path: Path) -> None:
        entries = self._load(yaml_path)
        local_path = yaml_path.parent / "correspondents.local.yaml"
        if local_path.exists():
            entries += self._load(local_path)
            logger.info("Loaded local correspondents from %s", local_path)

        self._alias_to_canonical: dict[str, str] = {}
        self._canonicals: list[str] = []
        for entry in entries:
            canonical: str = entry["canonical"]
            self._canonicals.append(canonical)
            self._alias_to_canonical[slugify(canonical)] = canonical
            for alias in entry.get("aliases", []):
                self._alias_to_canonical[slugify(alias)] = canonical

    @staticmethod
    def _load(path: Path) -> list[dict]:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or []

    @property
    def canonical_names(self) -> list[str]:
        return list(self._canonicals)

    def resolve_to_canonical(self, raw_name: str) -> str | None:
        """Return the canonical name if raw_name matches a known alias, else None."""
        return self._alias_to_canonical.get(slugify(raw_name))


class TagRegistry:
    """Loads tags from YAML and resolves id → display label in a given language."""

    def __init__(self, yaml_path: Path, language: str = "fr") -> None:
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._language = language
        self._system_ids: list[str] = [t["id"] for t in data.get("system", [])]
        self._id_to_label: dict[str, str] = {}
        for tag in data.get("system", []):
            self._id_to_label[tag["id"]] = tag["id"]
        for tag in data.get("business", []):
            tag_id: str = tag["id"]
            label: str = tag.get("labels", {}).get(language) or tag_id
            self._id_to_label[tag_id] = label

    def label(self, tag_id: str) -> str:
        """Return the display label for a given tag id."""
        return self._id_to_label.get(tag_id, tag_id)

    @property
    def all_ids(self) -> list[str]:
        return list(self._id_to_label.keys())


class ReferentialManager:
    """Orchestrates resolution of correspondents / tags / document types in Paperless.

    - Class A: exact match on canonical whitelist → returns Paperless entity id
    - Class B: auto-creation with Levenshtein guard against existing entries
    """

    def __init__(
        self,
        client: PaperlessClient,
        canonical_correspondents: CanonicalCorrespondents,
        document_type_registry: DocumentTypeRegistry,
        tag_registry: TagRegistry,
        levenshtein_threshold: float,
    ) -> None:
        self._client = client
        self._canonical = canonical_correspondents
        self._doc_types = document_type_registry
        self._tags_registry = tag_registry
        self._threshold = levenshtein_threshold
        self._refresh_caches()

    def _refresh_caches(self) -> None:
        """Reload correspondents / tags / document types from Paperless."""
        self._correspondents: dict[str, PaperlessCorrespondent] = {
            c.name: c for c in self._client.list_correspondents()
        }
        self._tags: dict[str, PaperlessTag] = {t.name: t for t in self._client.list_tags()}
        self._paperless_doc_types: dict[str, PaperlessDocumentType] = {
            t.name: t for t in self._client.list_document_types()
        }

    # ─────────────────────────────────────────── Correspondents

    def resolve_correspondent(self, raw_name: str) -> tuple[int, bool]:
        """Resolve a correspondent name to its Paperless id.

        Returns:
            (id, was_created): was_created=True if a new entry was created.
        """
        canonical = self._canonical.resolve_to_canonical(raw_name)
        if canonical is not None:
            if canonical in self._correspondents:
                return self._correspondents[canonical].id, False
            new = self._client.create_correspondent(canonical)
            self._correspondents[canonical] = new
            logger.info("Canonical correspondent created: %s", canonical)
            return new.id, True

        existing_match = fuzzy_match(raw_name, list(self._correspondents.keys()), self._threshold)
        if existing_match is not None:
            if existing_match != raw_name:
                logger.info("Fuzzy-matched correspondent: '%s' → '%s'", raw_name, existing_match)
            return self._correspondents[existing_match].id, False

        new = self._client.create_correspondent(raw_name)
        self._correspondents[raw_name] = new
        logger.info("New correspondent created (Class B): %s", raw_name)
        return new.id, True

    # ─────────────────────────────────────────── Document types

    def resolve_document_type(self, doc_id: str) -> int:
        """Resolve a document type id to its Paperless id.

        Creates the entry in Paperless if it does not exist yet.
        """
        label = self._doc_types.label(doc_id)
        if label in self._paperless_doc_types:
            return self._paperless_doc_types[label].id
        new = self._client.create_document_type(label)
        self._paperless_doc_types[label] = new
        logger.info("Document type created in Paperless: %s (%s)", label, doc_id)
        return new.id

    # ─────────────────────────────────────────── Tags

    def resolve_tag(self, tag_id: str) -> int:
        """Resolve a tag id to its Paperless id, creating it if needed."""
        label = self._tags_registry.label(tag_id)
        if label not in self._tags:
            new = self._client.create_tag(label)
            self._tags[label] = new
            logger.info("New tag created: %s (%s)", label, tag_id)
        return self._tags[label].id

    def resolve_tags(self, tag_ids: list[str]) -> list[int]:
        return [self.resolve_tag(t) for t in tag_ids]

    def tag_id(self, name: str) -> int:
        """Resolve a system tag that MUST already exist in Paperless."""
        if name not in self._tags:
            raise RuntimeError(f"Tag '{name}' not found. Run `make init-referential` first.")
        return self._tags[name].id
