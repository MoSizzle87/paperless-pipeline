"""Export des documents classifiés vers une arborescence prête pour Digiposte.

Lit les documents Paperless-ngx ayant le tag `ai:processed` (et optionnellement
`ai:a-verifier`), les copie depuis le stockage Paperless vers
`data/export/digiposte/` (à plat, organisé par type de document) avec renommage
selon la convention YYYY-MM_Type_Emetteur.pdf.

Comportement :
- Filtre : skip les docs taggés `digiposte:uploaded` (déjà uploadés dans Digiposte)
- Idempotent : si un fichier existe déjà à destination, il est skippé (pas écrasé)
- Cumulative : les nouveaux exports s'additionnent au contenu existant de digiposte/
- Génère un index.csv à la racine de digiposte/ (régénéré à chaque run)

Usage:
    docker compose exec classifier python scripts/export_digiposte.py [--include-review]

Options:
    --include-review  Inclut aussi les docs taggés `ai:a-verifier` (défaut: non)
"""

import argparse
import csv
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# Permet d'importer pipeline.* depuis n'importe où
sys.path.insert(0, "/app/src")

from pipeline.config import settings  # noqa: E402
from pipeline.logging_setup import setup_logging  # noqa: E402
from pipeline.paperless_client import PaperlessClient  # noqa: E402
from pipeline.schemas import PaperlessDocument  # noqa: E402

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path("/app/export/digiposte")
ARCHIVE_DIRNAME = "archive"  # sous-dossier réservé, ne pas y exporter


def slugify_for_path(text: str) -> str:
    """Slugifie une string pour usage en nom de dossier ou de fichier.

    - Suppression des accents (é → e, ç → c)
    - Espaces, slashes, apostrophes deviennent tirets
    - Caractères spéciaux supprimés
    - Tirets multiples collapsés
    - Casse préservée pour lisibilité
    """
    if not text:
        return "Inconnu"
    nfd = unicodedata.normalize("NFD", text)
    text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    text = re.sub(r"[/\\\s'\"]+", "-", text)
    text = re.sub(r"[^a-zA-Z0-9-]", "", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-") or "Inconnu"


def folder_name_for_type(document_type_name: str) -> str:
    """Convertit un nom de type Paperless en nom de dossier.

    Cas particulier : 'Document Pôle Emploi / France Travail' devient
    'France-Travail' pour rester lisible.
    """
    if document_type_name == "Document Pôle Emploi / France Travail":
        return "France-Travail"
    return slugify_for_path(document_type_name)


def filename_for_doc(
    created: str | None,
    document_type_name: str,
    correspondent_name: str | None,
) -> str:
    """Construit le nom de fichier YYYY-MM_Type_Emetteur.pdf."""
    if created:
        try:
            period = created[:7]
            datetime.strptime(period, "%Y-%m")
        except (ValueError, TypeError):
            period = "0000-00"
    else:
        period = "0000-00"

    type_slug = slugify_for_path(document_type_name)
    correspondent_slug = slugify_for_path(correspondent_name) if correspondent_name else "Inconnu"

    return f"{period}_{type_slug}_{correspondent_slug}.pdf"


def export_documents(
    client: PaperlessClient,
    output_dir: Path,
    include_review: bool,
) -> dict[str, int]:
    """Exporte les documents classifiés vers l'arborescence Digiposte.

    Retourne un dict de stats : exported, skipped_uploaded, skipped_no_type,
    skipped_already_exists, skipped_failed_download.
    """
    stats = {
        "exported": 0,
        "skipped_uploaded": 0,
        "skipped_no_type": 0,
        "skipped_already_exists": 0,
        "skipped_failed_download": 0,
    }

    # Récupère les IDs des tags système
    tags = {t.name: t.id for t in client.list_tags()}
    tag_processed = tags.get("ai:processed")
    tag_review = tags.get("ai:a-verifier")
    tag_uploaded = tags.get("digiposte:uploaded")

    if tag_processed is None:
        raise RuntimeError("Tag 'ai:processed' introuvable. Lance `make init-referential` d'abord.")
    if tag_uploaded is None:
        raise RuntimeError(
            "Tag 'digiposte:uploaded' introuvable. Lance `make init-referential` d'abord."
        )

    # Mapping ID → nom pour types et correspondants
    types_by_id = {t.id: t.name for t in client.list_document_types()}
    correspondents_by_id = {c.id: c.name for c in client.list_correspondents()}

    # Récupération des candidats (ai:processed + optionnellement ai:a-verifier)
    candidates: list[PaperlessDocument] = []
    candidates.extend(client.list_documents_with_tag(tag_processed))
    if include_review and tag_review is not None:
        candidates.extend(client.list_documents_with_tag(tag_review))

    # Déduplication (un doc peut avoir les deux tags)
    seen_ids: set[int] = set()
    unique_candidates: list[PaperlessDocument] = []
    for doc in candidates:
        if doc.id not in seen_ids:
            seen_ids.add(doc.id)
            unique_candidates.append(doc)

    logger.info("%d candidat(s) après déduplication", len(unique_candidates))

    output_dir.mkdir(parents=True, exist_ok=True)

    # Index CSV : on (re)génère à chaque run pour refléter l'état actuel de digiposte/
    # On va le construire en parcourant l'arbo finale après l'export
    new_files_in_run: list[dict[str, str]] = []

    for doc in unique_candidates:
        # Skip si déjà uploadé dans Digiposte
        if tag_uploaded in doc.tags:
            stats["skipped_uploaded"] += 1
            continue

        # Skip si pas de document_type (anomalie)
        if doc.document_type is None:
            logger.warning("Doc %d (%s) sans document_type, skip", doc.id, doc.title)
            stats["skipped_no_type"] += 1
            continue

        type_name = types_by_id.get(doc.document_type, "Autre")
        correspondent_name = (
            correspondents_by_id.get(doc.correspondent) if doc.correspondent is not None else None
        )

        folder_name = folder_name_for_type(type_name)
        filename = filename_for_doc(doc.created, type_name, correspondent_name)

        target_folder = output_dir / folder_name
        target_folder.mkdir(parents=True, exist_ok=True)
        target_path = target_folder / filename

        # Idempotence : si le fichier existe déjà, on skip
        if target_path.exists():
            stats["skipped_already_exists"] += 1
            logger.debug("  ⏭  Déjà présent : %s/%s", folder_name, filename)
            continue

        # Téléchargement du PDF depuis Paperless
        try:
            pdf_bytes = client.download_document(doc.id)
        except Exception as e:  # noqa: BLE001
            logger.error("Échec téléchargement doc %d : %s", doc.id, e)
            stats["skipped_failed_download"] += 1
            continue

        target_path.write_bytes(pdf_bytes)
        logger.info("  ✓ %s/%s", folder_name, filename)

        new_files_in_run.append(
            {
                "doc_id": str(doc.id),
                "type": type_name,
                "correspondent": correspondent_name or "",
                "created": doc.created or "",
                "folder": folder_name,
                "filename": filename,
                "title": doc.title,
            }
        )
        stats["exported"] += 1

    # Régénère l'index complet (tous les fichiers présents dans digiposte/)
    write_global_index(output_dir)

    return stats


def write_global_index(output_dir: Path) -> None:
    """Régénère un index.csv listant tous les fichiers présents dans digiposte/.

    Parcourt l'arborescence (sauf le dossier archive/) et liste tous les PDF.
    """
    index_path = output_dir / "index.csv"
    rows: list[dict[str, str]] = []

    for folder in sorted(output_dir.iterdir()):
        if not folder.is_dir() or folder.name == ARCHIVE_DIRNAME:
            continue
        for pdf in sorted(folder.iterdir()):
            if pdf.suffix.lower() != ".pdf":
                continue
            # Tente de parser le nom : YYYY-MM_Type_Emetteur.pdf
            stem = pdf.stem
            parts = stem.split("_", 2)
            period = parts[0] if len(parts) >= 1 else ""
            type_slug = parts[1] if len(parts) >= 2 else ""
            correspondent_slug = parts[2] if len(parts) >= 3 else ""

            rows.append(
                {
                    "folder": folder.name,
                    "filename": pdf.name,
                    "period": period,
                    "type": type_slug,
                    "correspondent": correspondent_slug,
                    "size_bytes": str(pdf.stat().st_size),
                }
            )

    if rows:
        with index_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["folder", "filename", "period", "type", "correspondent", "size_bytes"],
            )
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Index global mis à jour : %s (%d fichiers présents)", index_path, len(rows))
    elif index_path.exists():
        # Plus aucun fichier → on supprime l'index obsolète
        index_path.unlink()
        logger.info("digiposte/ vide : index.csv supprimé")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Paperless → arborescence Digiposte")
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="Inclut aussi les documents taggés `ai:a-verifier` (défaut: non)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EXPORT_ROOT,
        help=f"Dossier de sortie (défaut: {EXPORT_ROOT})",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Export Digiposte ===")
    logger.info("Sortie               : %s", args.output)
    logger.info("Inclut docs à vérifier : %s", args.include_review)

    with PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    ) as client:
        stats = export_documents(client, args.output, args.include_review)

    logger.info("\n✅ Export terminé")
    logger.info("  Nouveaux exportés       : %d", stats["exported"])
    logger.info("  Skip (déjà uploadés)    : %d", stats["skipped_uploaded"])
    logger.info("  Skip (déjà présents)    : %d", stats["skipped_already_exists"])
    logger.info("  Skip (sans type)        : %d", stats["skipped_no_type"])
    logger.info("  Skip (DL échoué)        : %d", stats["skipped_failed_download"])
    logger.info("  Dossier                 : %s", args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
