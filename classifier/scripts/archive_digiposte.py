"""Archive le contenu courant de data/export/digiposte/ vers un sous-dossier
horodaté dans data/export/digiposte/archive/.

Génère un README.md auto-documenté à la racine de l'archive avec un résumé
des contenus (nombre de docs par catégorie, total, date d'archivage).

Usage:
    docker compose exec classifier python scripts/archive_digiposte.py
"""

import argparse
import logging
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Permet d'importer pipeline.* depuis n'importe où
sys.path.insert(0, "/app/src")

from pipeline.config import settings  # noqa: E402
from pipeline.logging_setup import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)

EXPORT_ROOT = Path("/app/export/digiposte")
ARCHIVE_DIRNAME = "archive"


def gather_stats(source_dir: Path) -> tuple[int, Counter[str]]:
    """Compte les fichiers PDF par dossier dans source_dir.

    Returns:
        (total_files, counter_by_folder)
    """
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
    """Génère un README.md auto-documenté à la racine de l'archive."""
    lines = [
        f"# Archive Digiposte du {timestamp}",
        "",
        f"Cette archive contient les documents qui étaient présents dans",
        f"`data/export/digiposte/` au moment de la commande `make archive-digiposte`.",
        "",
        "## Résumé",
        "",
        f"- Date d'archivage : {timestamp}",
        f"- Nombre total de documents : {total}",
        f"- Nombre de catégories : {len(counter)}",
        "",
        "## Détail par catégorie",
        "",
    ]
    for folder_name, count in counter.most_common():
        lines.append(f"- **{folder_name}** : {count} document(s)")
    lines.extend(
        [
            "",
            "## Index complet",
            "",
            "Voir `index.csv` pour la liste détaillée doc par doc.",
            "",
        ]
    )
    readme_path = archive_dir / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")


def archive_current(source_dir: Path) -> int:
    """Archive le contenu actuel de source_dir vers source_dir/archive/<timestamp>/.

    Returns:
        Nombre de fichiers déplacés.
    """
    if not source_dir.exists():
        logger.warning("Dossier source inexistant : %s", source_dir)
        return 0

    # Stats avant déplacement
    total, counter = gather_stats(source_dir)
    if total == 0:
        logger.info("Rien à archiver : aucun document dans %s", source_dir)
        return 0

    # Création du dossier d'archive horodaté
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_root = source_dir / ARCHIVE_DIRNAME
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_dir = archive_root / timestamp
    archive_dir.mkdir(parents=True, exist_ok=False)

    logger.info("Archivage vers %s", archive_dir)
    logger.info("  %d documents répartis dans %d catégorie(s)", total, len(counter))

    # Déplacement de chaque dossier de catégorie + index.csv
    for item in sorted(source_dir.iterdir()):
        if item.name == ARCHIVE_DIRNAME:
            continue
        target = archive_dir / item.name
        shutil.move(str(item), str(target))
        logger.debug("  → %s", item.name)

    # README généré dans le dossier d'archive
    write_readme(archive_dir, total, counter, timestamp)
    logger.info("README généré : %s", archive_dir / "README.md")

    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive le contenu courant de digiposte/ vers archive/<timestamp>/"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=EXPORT_ROOT,
        help=f"Dossier source à archiver (défaut: {EXPORT_ROOT})",
    )
    args = parser.parse_args()

    setup_logging(settings.log_level, settings.log_dir)
    logger.info("=== Archive Digiposte ===")

    moved = archive_current(args.source)

    if moved > 0:
        logger.info("\n✅ Archive terminée (%d documents déplacés)", moved)
    else:
        logger.info("\n⏭  Aucune action effectuée")

    return 0


if __name__ == "__main__":
    sys.exit(main())
