"""Archive the current export directory to a timestamped subdirectory.

Moves all content from the export root into:
    <export_root>/archive/<YYYY-MM-DD_HH-MM-SS>/

Generates a README.md in the archive with a summary of archived content.

Usage:
    docker compose exec classifier python scripts/archive.py [--source PATH]
"""

import argparse
import logging
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from filethat.config import settings  # noqa: E402
from filethat.logging_setup import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path("/app/export")
ARCHIVE_DIRNAME = "archive"


def gather_stats(source_dir: Path) -> tuple[int, Counter[str]]:
    """Count PDF files per folder in source_dir, excluding the archive folder."""
    counter: Counter[str] = Counter()
    total = 0
    for folder in sorted(source_dir.iterdir()):
        if not folder.is_dir() or folder.name == ARCHIVE_DIRNAME:
            continue
        pdf_count = sum(1 for f in folder.iterdir() if f.suffix.lower() == ".pdf")
        if pdf_count > 0:
            counter[folder.name] = pdf_count
            total += pdf_count
    return total, counter


def write_readme(archive_dir: Path, total: int, counter: Counter[str], timestamp: str) -> None:
    """Generate a README.md summarising the archived content."""
    lines = [
        f"# Archive — {timestamp}",
        "",
        "This archive contains documents that were present in the export directory",
        "at the time the `make archive` command was run.",
        "",
        "## Summary",
        "",
        f"- Archived on    : {timestamp}",
        f"- Total documents: {total}",
        f"- Categories     : {len(counter)}",
        "",
        "## Breakdown by category",
        "",
    ]
    for folder_name, count in counter.most_common():
        lines.append(f"- **{folder_name}**: {count} document(s)")
    lines.extend(
        [
            "",
            "## Full index",
            "",
            "See `index.csv` for a detailed per-document listing.",
            "",
        ]
    )
    (archive_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def archive_current(source_dir: Path) -> int:
    """Move current export content to a timestamped archive subdirectory.

    Returns:
        Number of files moved.
    """
    if not source_dir.exists():
        logger.warning("Source directory does not exist: %s", source_dir)
        return 0

    total, counter = gather_stats(source_dir)
    if total == 0:
        logger.info("Nothing to archive: no documents in %s", source_dir)
        return 0

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_root = source_dir / ARCHIVE_DIRNAME
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_dir = archive_root / timestamp
    archive_dir.mkdir(parents=True, exist_ok=False)

    logger.info("Archiving to %s", archive_dir)
    logger.info("  %d documents across %d category/ies", total, len(counter))

    for item in sorted(source_dir.iterdir()):
        if item.name == ARCHIVE_DIRNAME:
            continue
        shutil.move(str(item), str(archive_dir / item.name))
        logger.debug("  Moved: %s", item.name)

    write_readme(archive_dir, total, counter, timestamp)
    logger.info("README generated: %s", archive_dir / "README.md")

    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive current export content to a timestamped subdirectory"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=EXPORT_ROOT,
        help=f"Export directory to archive (default: {EXPORT_ROOT})",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Archive ===")

    moved = archive_current(args.source)

    if moved > 0:
        logger.info("=== Archive complete (%d documents moved) ===", moved)
    else:
        logger.info("=== No action taken ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
