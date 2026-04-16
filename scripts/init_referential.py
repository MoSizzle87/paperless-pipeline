"""Script one-shot : crée dans Paperless-ngx les correspondants canoniques,
les types de documents et les tags définis dans les YAML.

Idempotent : peut être relancé sans risque (skip si déjà existant).
"""

import logging
import sys
from pathlib import Path

import yaml

# Permet d'importer pipeline.* depuis n'importe où
sys.path.insert(0, "/app/src")

from pipeline.config import settings  # noqa: E402
from pipeline.logging_setup import setup_logging  # noqa: E402
from pipeline.paperless_client import PaperlessClient  # noqa: E402

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_document_types(client: PaperlessClient, types_yaml: Path) -> None:
    existing = {t.name for t in client.list_document_types()}
    wanted = load_yaml(types_yaml)
    for entry in wanted:
        name = entry["name"]
        if name in existing:
            logger.info("  [skip] type déjà présent : %s", name)
            continue
        client.create_document_type(name)
        logger.info("  [create] type : %s", name)


def init_tags(client: PaperlessClient, tags_yaml: Path) -> None:
    existing = {t.name for t in client.list_tags()}
    data = load_yaml(tags_yaml)
    # data est un dict ici (system/business), pas une liste
    if isinstance(data, list):
        raise ValueError("tags.yaml doit être un dict avec clés 'system' et 'business'")

    for group in ("system", "business"):
        for entry in data.get(group, []):
            name = entry["name"]
            color = entry.get("color", "#808080")
            if name in existing:
                logger.info("  [skip] tag déjà présent : %s", name)
                continue
            client.create_tag(name, color=color)
            logger.info("  [create] tag (%s) : %s", group, name)


def init_correspondents(client: PaperlessClient, correspondents_yaml: Path) -> None:
    existing = {c.name for c in client.list_correspondents()}
    wanted = load_yaml(correspondents_yaml)
    for entry in wanted:
        canonical = entry["canonical"]
        if canonical in existing:
            logger.info("  [skip] correspondant déjà présent : %s", canonical)
            continue
        client.create_correspondent(canonical)
        logger.info("  [create] correspondant : %s", canonical)


def main() -> int:
    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Initialisation du référentiel Paperless-ngx ===")

    ref_dir = settings.referentials_dir
    with PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    ) as client:
        logger.info("\n→ Types de documents")
        init_document_types(client, ref_dir / "document_types.yaml")

        logger.info("\n→ Tags")
        init_tags(client, ref_dir / "tags.yaml")

        logger.info("\n→ Correspondants canoniques (Classe A)")
        init_correspondents(client, ref_dir / "correspondents_canonical.yaml")

    logger.info("\n✅ Référentiel initialisé avec succès")
    return 0


if __name__ == "__main__":
    sys.exit(main())
