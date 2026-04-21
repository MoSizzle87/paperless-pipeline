"""One-shot script: creates canonical correspondents, document types and tags in Paperless-ngx.

Idempotent: safe to re-run (skips already existing entries).
"""

import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, "/app/src")

from filethat.config import settings  # noqa: E402
from filethat.logging_setup import setup_logging  # noqa: E402
from filethat.paperless_client import PaperlessClient  # noqa: E402
from filethat.referential import DocumentTypeRegistry  # noqa: E402
from filethat.referential import TagRegistry

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> list[dict] | dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_document_types(client: PaperlessClient, types_yaml: Path, language: str) -> None:
    """Create document types in Paperless using the label for the configured language."""
    existing = {t.name for t in client.list_document_types()}
    registry = DocumentTypeRegistry(types_yaml, language=language)
    for doc_id in registry.ids:
        label = registry.label(doc_id)
        if label in existing:
            logger.info("  [skip] document type already present: %s", label)
            continue
        client.create_document_type(label)
        logger.info("  [create] document type: %s (%s)", label, doc_id)


def init_tags(client: PaperlessClient, tags_yaml: Path, language: str) -> None:
    """Create system and business tags in Paperless."""
    existing = {t.name for t in client.list_tags()}
    data = load_yaml(tags_yaml)
    if isinstance(data, list):
        raise ValueError("tags.yaml must be a dict with 'system' and 'business' keys")

    # System tags — id is the tag name, no translation
    for entry in data.get("system", []):
        tag_id: str = entry["id"]
        color: str = entry.get("color", "#808080")
        if tag_id in existing:
            logger.info("  [skip] system tag already present: %s", tag_id)
            continue
        client.create_tag(tag_id, color=color)
        logger.info("  [create] system tag: %s", tag_id)

    # Business tags — use label in configured language
    registry = TagRegistry(tags_yaml, language=language)
    for entry in data.get("business", []):
        tag_id = entry["id"]
        label = registry.label(tag_id)
        color = entry.get("color", "#808080")
        if label in existing:
            logger.info("  [skip] business tag already present: %s", label)
            continue
        client.create_tag(label, color=color)
        logger.info("  [create] business tag: %s (%s)", label, tag_id)


def init_correspondents(client: PaperlessClient, correspondents_yaml: Path) -> None:
    """Create canonical correspondents (Class A) in Paperless."""
    existing = {c.name for c in client.list_correspondents()}
    entries = yaml.safe_load(correspondents_yaml.read_text(encoding="utf-8")) or []

    # Merge local overrides if present
    local_path = correspondents_yaml.parent / "correspondents.local.yaml"
    if local_path.exists():
        local_entries = yaml.safe_load(local_path.read_text(encoding="utf-8")) or []
        entries += local_entries
        logger.info("  Loaded local correspondents from %s", local_path)

    for entry in entries:
        canonical: str = entry["canonical"]
        if canonical in existing:
            logger.info("  [skip] correspondent already present: %s", canonical)
            continue
        client.create_correspondent(canonical)
        logger.info("  [create] correspondent: %s", canonical)


def main() -> int:
    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Paperless-ngx referential initialization ===")

    ref_dir = settings.referentials_dir
    language = settings.language

    with PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    ) as client:
        logger.info("\n→ Document types")
        init_document_types(client, ref_dir / "document_types.yaml", language)

        logger.info("\n→ Tags")
        init_tags(client, ref_dir / "tags.yaml", language)

        logger.info("\n→ Canonical correspondents (Class A)")
        init_correspondents(client, ref_dir / "correspondents.yaml")

    logger.info("\n=== Referential initialized successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
