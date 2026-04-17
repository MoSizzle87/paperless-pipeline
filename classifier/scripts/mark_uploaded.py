"""Marque comme `digiposte:uploaded` tous les documents Paperless dont le PDF
correspondant est présent dans data/export/digiposte/.

Logique : pour chaque PDF dans digiposte/<categorie>/<filename>.pdf, on
recompose le nom attendu (YYYY-MM_Type_Emetteur.pdf) pour les docs ayant le tag
`ai:processed` et on tagge ceux qui matchent.

Usage:
    docker compose exec classifier python scripts/mark_uploaded.py [--dry-run]

Options:
    --dry-run  Affiche ce qui serait taggé sans modifier Paperless
"""

import argparse
import logging
import sys
from pathlib import Path

# Permet d'importer pipeline.* depuis n'importe où
sys.path.insert(0, "/app/src")

from pipeline.config import settings  # noqa: E402
from pipeline.logging_setup import setup_logging  # noqa: E402
from pipeline.paperless_client import PaperlessClient  # noqa: E402

# Réutilise les helpers du script d'export pour cohérence
sys.path.insert(0, "/app/scripts")
from export_digiposte import filename_for_doc  # noqa: E402
from export_digiposte import ARCHIVE_DIRNAME, folder_name_for_type

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path("/app/export/digiposte")


def collect_present_files(source_dir: Path) -> set[tuple[str, str]]:
    """Collecte les (folder_name, filename) actuellement présents dans source_dir.

    Returns:
        Set de tuples (nom_dossier, nom_fichier) pour matching ultérieur.
    """
    present: set[tuple[str, str]] = set()
    if not source_dir.exists():
        return present
    for folder in source_dir.iterdir():
        if not folder.is_dir() or folder.name == ARCHIVE_DIRNAME:
            continue
        for pdf in folder.iterdir():
            if pdf.suffix.lower() == ".pdf":
                present.add((folder.name, pdf.name))
    return present


def mark_uploaded(client: PaperlessClient, source_dir: Path, dry_run: bool) -> dict[str, int]:
    """Tagge `digiposte:uploaded` les docs Paperless dont le PDF est dans source_dir.

    Returns:
        dict de stats : {present, matched, tagged, already_tagged, no_match}
    """
    stats = {"present": 0, "matched": 0, "tagged": 0, "already_tagged": 0, "no_match": 0}

    # Collecte des fichiers présents dans digiposte/
    present_files = collect_present_files(source_dir)
    stats["present"] = len(present_files)
    logger.info("%d fichier(s) PDF présent(s) dans %s", stats["present"], source_dir)

    if not present_files:
        return stats

    # Récupère les tags système et les mappings ID → nom
    tags = {t.name: t.id for t in client.list_tags()}
    tag_processed = tags.get("ai:processed")
    tag_uploaded = tags.get("digiposte:uploaded")
    if tag_processed is None or tag_uploaded is None:
        raise RuntimeError(
            "Tags 'ai:processed' ou 'digiposte:uploaded' introuvables. "
            "Lance `make init-referential` d'abord."
        )

    types_by_id = {t.id: t.name for t in client.list_document_types()}
    correspondents_by_id = {c.id: c.name for c in client.list_correspondents()}

    # Tous les docs taggés ai:processed (candidats potentiels)
    candidates = client.list_documents_with_tag(tag_processed)
    logger.info("%d candidat(s) taggé(s) ai:processed dans Paperless", len(candidates))

    # Matching : pour chaque candidat, on calcule le folder/filename attendu
    # et on vérifie s'il est présent dans le dossier
    for doc in candidates:
        if doc.document_type is None:
            continue
        type_name = types_by_id.get(doc.document_type, "Autre")
        correspondent_name = (
            correspondents_by_id.get(doc.correspondent) if doc.correspondent is not None else None
        )
        expected_folder = folder_name_for_type(type_name)
        expected_filename = filename_for_doc(doc.created, type_name, correspondent_name)

        if (expected_folder, expected_filename) not in present_files:
            stats["no_match"] += 1
            continue

        stats["matched"] += 1

        # Déjà taggé ?
        if tag_uploaded in doc.tags:
            stats["already_tagged"] += 1
            logger.debug("  ⏭  Déjà taggé : doc %d", doc.id)
            continue

        if dry_run:
            logger.info("  [DRY-RUN] Doc %d : %s/%s", doc.id, expected_folder, expected_filename)
        else:
            client.add_tag(doc.id, tag_uploaded)
            logger.info("  ✓ Doc %d taggé : %s/%s", doc.id, expected_folder, expected_filename)
        stats["tagged"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tagge `digiposte:uploaded` les docs Paperless dont le PDF est dans digiposte/"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=EXPORT_ROOT,
        help=f"Dossier contenant les PDFs uploadés (défaut: {EXPORT_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche ce qui serait taggé sans modifier Paperless",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Mark uploaded ===")
    if args.dry_run:
        logger.info("Mode DRY-RUN : aucune modification ne sera apportée")

    with PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    ) as client:
        stats = mark_uploaded(client, args.source, args.dry_run)

    logger.info("\n✅ Mark uploaded terminé")
    logger.info("  PDF présents dans digiposte/ : %d", stats["present"])
    logger.info("  Matchés avec Paperless       : %d", stats["matched"])
    logger.info("  Déjà taggés (skip)           : %d", stats["already_tagged"])
    logger.info("  Nouvellement taggés          : %d", stats["tagged"] - stats["already_tagged"])
    if stats["no_match"] > 0:
        logger.warning(
            "  Sans match (anomalie)        : %d candidats Paperless sans PDF correspondant",
            stats["no_match"],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
