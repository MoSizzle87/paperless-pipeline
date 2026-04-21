"""Export classified documents to a folder hierarchy ready for external upload.

Reads Paperless-ngx documents tagged `ai:processed` (and optionally `ai:to-check`),
downloads their PDFs and organises them under the export root as:
    <export_root>/<DocumentType>/<YYYY-MM>_<Type>_<Correspondent>.pdf

Behaviour:
- Skips documents tagged `workflow:exported` (already exported)
- Idempotent: existing files are never overwritten
- Cumulative: new exports are added to existing content
- Regenerates index.csv at the export root on every run

Usage:
    docker compose exec classifier python scripts/export.py [--include-review]

Options:
    --include-review  Also include documents tagged `ai:to-check` (default: no)
    --output PATH     Export root directory (default: /app/export)
"""

import argparse
import csv
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from filethat.config import settings  # noqa: E402
from filethat.logging_setup import setup_logging  # noqa: E402
from filethat.paperless_client import PaperlessClient  # noqa: E402
from filethat.schemas import PaperlessDocument  # noqa: E402

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path("/app/export")
ARCHIVE_DIRNAME = "archive"


def slugify_for_path(text: str) -> str:
    """Slugify a string for use as a folder or file name.

    - Removes accents (é → e, ç → c)
    - Spaces, slashes and apostrophes become hyphens
    - Special characters are removed
    - Consecutive hyphens are collapsed
    - Original casing is preserved for readability
    """
    if not text:
        return "Unknown"
    nfd = unicodedata.normalize("NFD", text)
    text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    text = re.sub(r"[/\\\s'\"]+", "-", text)
    text = re.sub(r"[^a-zA-Z0-9-]", "", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-") or "Unknown"


def folder_name_for_type(document_type_label: str) -> str:
    """Convert a Paperless document type label to a folder name."""
    return slugify_for_path(document_type_label)


def filename_for_doc(
    created: str | None,
    document_type_label: str,
    correspondent_name: str | None,
) -> str:
    """Build the export filename: YYYY-MM_Type_Correspondent.pdf."""
    if created:
        try:
            period = created[:7]
            datetime.strptime(period, "%Y-%m")
        except (ValueError, TypeError):
            period = "0000-00"
    else:
        period = "0000-00"

    type_slug = slugify_for_path(document_type_label)
    correspondent_slug = slugify_for_path(correspondent_name) if correspondent_name else "Unknown"
    return f"{period}_{type_slug}_{correspondent_slug}.pdf"


def export_documents(
    client: PaperlessClient,
    output_dir: Path,
    include_review: bool,
) -> dict[str, int]:
    """Export classified documents to the output directory.

    Returns a stats dict: exported, skipped_exported, skipped_no_type,
    skipped_already_exists, skipped_failed_download.
    """
    stats = {
        "exported": 0,
        "skipped_exported": 0,
        "skipped_no_type": 0,
        "skipped_already_exists": 0,
        "skipped_failed_download": 0,
    }

    tags = {t.name: t.id for t in client.list_tags()}
    tag_processed = tags.get("ai:processed")
    tag_review = tags.get("ai:to-check")
    tag_exported = tags.get("workflow:exported")

    if tag_processed is None:
        raise RuntimeError("Tag 'ai:processed' not found. Run `make init-referential` first.")
    if tag_exported is None:
        raise RuntimeError("Tag 'workflow:exported' not found. Run `make init-referential` first.")

    types_by_id = {t.id: t.name for t in client.list_document_types()}
    correspondents_by_id = {c.id: c.name for c in client.list_correspondents()}

    candidates: list[PaperlessDocument] = []
    candidates.extend(client.list_documents_with_tag(tag_processed))
    if include_review and tag_review is not None:
        candidates.extend(client.list_documents_with_tag(tag_review))

    # Deduplicate
    seen_ids: set[int] = set()
    unique_candidates: list[PaperlessDocument] = []
    for doc in candidates:
        if doc.id not in seen_ids:
            seen_ids.add(doc.id)
            unique_candidates.append(doc)

    logger.info("%d candidate(s) after deduplication", len(unique_candidates))
    output_dir.mkdir(parents=True, exist_ok=True)

    for doc in unique_candidates:
        if tag_exported in doc.tags:
            stats["skipped_exported"] += 1
            continue

        if doc.document_type is None:
            logger.warning("Doc %d (%s) has no document_type, skipping", doc.id, doc.title)
            stats["skipped_no_type"] += 1
            continue

        type_label = types_by_id.get(doc.document_type, "Other")
        correspondent_name = (
            correspondents_by_id.get(doc.correspondent) if doc.correspondent is not None else None
        )

        folder_name = folder_name_for_type(type_label)
        filename = filename_for_doc(doc.created, type_label, correspondent_name)

        target_folder = output_dir / folder_name
        target_folder.mkdir(parents=True, exist_ok=True)
        target_path = target_folder / filename

        if target_path.exists():
            stats["skipped_already_exists"] += 1
            logger.debug("Already present: %s/%s", folder_name, filename)
            continue

        try:
            pdf_bytes = client.download_document(doc.id)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to download doc %d: %s", doc.id, e)
            stats["skipped_failed_download"] += 1
            continue

        target_path.write_bytes(pdf_bytes)
        logger.info("Exported: %s/%s", folder_name, filename)
        stats["exported"] += 1

    write_global_index(output_dir)
    return stats


def write_global_index(output_dir: Path) -> None:
    """Regenerate index.csv listing all PDF files currently in the export directory."""
    index_path = output_dir / "index.csv"
    rows: list[dict[str, str]] = []

    for folder in sorted(output_dir.iterdir()):
        if not folder.is_dir() or folder.name == ARCHIVE_DIRNAME:
            continue
        for pdf in sorted(folder.iterdir()):
            if pdf.suffix.lower() != ".pdf":
                continue
            stem = pdf.stem
            parts = stem.split("_", 2)
            rows.append(
                {
                    "folder": folder.name,
                    "filename": pdf.name,
                    "period": parts[0] if len(parts) >= 1 else "",
                    "type": parts[1] if len(parts) >= 2 else "",
                    "correspondent": parts[2] if len(parts) >= 3 else "",
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
        logger.info("Index updated: %s (%d files)", index_path, len(rows))
    elif index_path.exists():
        index_path.unlink()
        logger.info("Export directory empty: index.csv removed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export classified Paperless documents to a folder hierarchy"
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="Also include documents tagged `ai:to-check` (default: no)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EXPORT_ROOT,
        help=f"Export root directory (default: {EXPORT_ROOT})",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Export ===")
    logger.info("Output directory : %s", args.output)
    logger.info("Include to-check : %s", args.include_review)

    with PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    ) as client:
        stats = export_documents(client, args.output, args.include_review)

    logger.info("=== Export complete ===")
    logger.info("  Exported             : %d", stats["exported"])
    logger.info("  Skipped (exported)   : %d", stats["skipped_exported"])
    logger.info("  Skipped (exists)     : %d", stats["skipped_already_exists"])
    logger.info("  Skipped (no type)    : %d", stats["skipped_no_type"])
    logger.info("  Skipped (DL failed)  : %d", stats["skipped_failed_download"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
