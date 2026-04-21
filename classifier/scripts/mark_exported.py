"""Tag as `workflow:exported` all Paperless documents whose PDF is present in the export directory.

For each PDF found under <export_root>/<category>/<filename>.pdf, the script
reconstructs the expected filename for each `ai:processed` document and tags
matching ones as `workflow:exported`.

Usage:
    docker compose exec classifier python scripts/mark_exported.py [--dry-run]

Options:
    --dry-run   Show what would be tagged without modifying Paperless
    --source    Export root directory (default: /app/export)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

from filethat.config import settings  # noqa: E402
from filethat.logging_setup import setup_logging  # noqa: E402
from filethat.paperless_client import PaperlessClient  # noqa: E402

sys.path.insert(0, "/app/scripts")
from export import filename_for_doc  # noqa: E402
from export import ARCHIVE_DIRNAME, folder_name_for_type

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path("/app/export")


def collect_present_files(source_dir: Path) -> set[tuple[str, str]]:
    """Collect (folder_name, filename) tuples for all PDFs currently in source_dir."""
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


def mark_exported(client: PaperlessClient, source_dir: Path, dry_run: bool) -> dict[str, int]:
    """Tag `workflow:exported` on Paperless documents whose PDF exists in source_dir.

    Returns a stats dict: present, matched, tagged, already_tagged, no_match.
    """
    stats = {
        "present": 0,
        "matched": 0,
        "tagged": 0,
        "already_tagged": 0,
        "no_match": 0,
    }

    present_files = collect_present_files(source_dir)
    stats["present"] = len(present_files)
    logger.info("%d PDF file(s) found in %s", stats["present"], source_dir)

    if not present_files:
        return stats

    tags = {t.name: t.id for t in client.list_tags()}
    tag_processed = tags.get("ai:processed")
    tag_exported = tags.get("workflow:exported")

    if tag_processed is None or tag_exported is None:
        raise RuntimeError(
            "Tags 'ai:processed' or 'workflow:exported' not found. "
            "Run `make init-referential` first."
        )

    types_by_id = {t.id: t.name for t in client.list_document_types()}
    correspondents_by_id = {c.id: c.name for c in client.list_correspondents()}

    candidates = client.list_documents_with_tag(tag_processed)
    logger.info("%d candidate(s) tagged ai:processed in Paperless", len(candidates))

    for doc in candidates:
        if doc.document_type is None:
            continue
        type_label = types_by_id.get(doc.document_type, "Other")
        correspondent_name = (
            correspondents_by_id.get(doc.correspondent) if doc.correspondent is not None else None
        )
        expected_folder = folder_name_for_type(type_label)
        expected_filename = filename_for_doc(doc.created, type_label, correspondent_name)

        if (expected_folder, expected_filename) not in present_files:
            stats["no_match"] += 1
            continue

        stats["matched"] += 1

        if tag_exported in doc.tags:
            stats["already_tagged"] += 1
            logger.debug("Already tagged: doc %d", doc.id)
            continue

        if dry_run:
            logger.info(
                "[DRY-RUN] Would tag doc %d: %s/%s", doc.id, expected_folder, expected_filename
            )
        else:
            client.add_tag(doc.id, tag_exported)
            logger.info("Tagged: doc %d — %s/%s", doc.id, expected_folder, expected_filename)
        stats["tagged"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tag `workflow:exported` on documents whose PDF is in the export directory"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=EXPORT_ROOT,
        help=f"Export directory to scan (default: {EXPORT_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be tagged without modifying Paperless",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Mark exported ===")
    if args.dry_run:
        logger.info("DRY-RUN mode: no changes will be made")

    with PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    ) as client:
        stats = mark_exported(client, args.source, args.dry_run)

    logger.info("=== Mark exported complete ===")
    logger.info("  PDFs in export dir   : %d", stats["present"])
    logger.info("  Matched in Paperless : %d", stats["matched"])
    logger.info("  Already tagged       : %d", stats["already_tagged"])
    logger.info("  Newly tagged         : %d", stats["tagged"] - stats["already_tagged"])
    if stats["no_match"] > 0:
        logger.warning(
            "  No match (anomaly)   : %d Paperless docs with no corresponding PDF",
            stats["no_match"],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
