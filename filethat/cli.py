from __future__ import annotations

import argparse
import csv
import fcntl
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from filethat.config import Config
from filethat.logging_setup import setup_logging

logger = logging.getLogger(__name__)


@contextmanager
def _scan_lock(data_dir: Path) -> Generator[None, None, None]:
    lock_path = data_dir / ".filethat.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"Another scan is already running (lock file: {lock_path}). Exiting.")
            sys.exit(1)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def cmd_scan(config: Config) -> None:
    from filethat.journal import Journal
    from filethat.pipeline import _sha256, process_file

    data_dir = config.paths.journal.parent
    config.paths.review.mkdir(parents=True, exist_ok=True)
    with _scan_lock(data_dir):
        inbox = config.paths.inbox
        files = sorted(f for f in inbox.iterdir() if f.is_file() and not f.name.startswith("."))

        if not files:
            print("Nothing to process.")
            return

        journal = Journal(config.paths.journal)

        # Pre-filter: compute hashes up-front and skip already-journaled files
        # before spending time on OCR.
        to_process: list[Path] = []
        for f in files:
            if journal.has_hash(_sha256(f)):
                logger.info("Skipping already-processed file", extra={"file": str(f)})
            else:
                to_process.append(f)

        if not to_process:
            print("Nothing new to process.")
            return

        processed = 0
        for f in to_process:
            try:
                process_file(f, config, journal)
                processed += 1
            except Exception as exc:
                logger.error("Unhandled error", extra={"file": str(f), "error": str(exc)})

        print(f"Processed {processed} of {len(to_process)} file(s).")


def cmd_ui(config: Config) -> None:
    import uvicorn

    from filethat.web.app import create_app

    app = create_app(config)
    print(f"UI available at http://localhost:{config.web.port}")
    uvicorn.run(app, host=config.web.host, port=config.web.port)


def cmd_stats(config: Config) -> None:
    journal_path = config.paths.journal
    if not journal_path.exists():
        print("No journal found.")
        return

    total = success = errors = low_conf = review = 0
    with open(journal_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            if row["status"] == "success":
                success += 1
                try:
                    if float(row.get("confidence") or 1) < 0.7:
                        low_conf += 1
                except ValueError:
                    pass
            elif row["status"] == "review":
                review += 1
            else:
                errors += 1

    print(f"Total:          {total}")
    print(f"Success:        {success}")
    print(f"Review:         {review}")
    print(f"Errors:         {errors}")
    print(f"Low confidence: {low_conf} (< 0.7, among successes)")


def cmd_archive(config: Config) -> None:
    library = config.paths.library
    archive = config.paths.archive
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    dest = archive / ts
    dest.mkdir(parents=True, exist_ok=True)

    moved = 0
    for item in library.iterdir():
        if item.name.startswith("."):
            continue
        shutil.move(str(item), str(dest / item.name))
        moved += 1

    print(f"Archived {moved} item(s) to {dest}")


def cmd_delete_archive(config: Config, yes: bool) -> None:
    archive = config.paths.archive
    if not yes:
        answer = input("Delete all archives? [y/N] ").strip()
        if answer.lower() != "y":
            print("Aborted.")
            return

    count = 0
    for item in archive.iterdir():
        if item.name.startswith("."):
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
        count += 1

    print(f"Deleted {count} archive(s).")


def cmd_clean_failed(config: Config, yes: bool) -> None:
    failed = config.paths.failed
    if not yes:
        answer = input("Delete all failed entries? [y/N] ").strip()
        if answer.lower() != "y":
            print("Aborted.")
            return

    count = 0
    for item in failed.iterdir():
        if item.name.startswith("."):
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
        count += 1

    print(f"Deleted {count} failed entry/entries.")


def cmd_reset(config: Config, yes: bool) -> None:
    if not yes:
        print("WARNING: This will WIPE inbox, library, failed, archive and journal.")
        a1 = input("Are you sure? [y/N] ").strip()
        if a1.lower() != "y":
            print("Aborted.")
            return
        a2 = input("Really sure? Type 'yes' to confirm: ").strip()
        if a2 != "yes":
            print("Aborted.")
            return

    for d in (
        config.paths.inbox,
        config.paths.library,
        config.paths.failed,
        config.paths.archive,
    ):
        for item in d.iterdir():
            if item.name.startswith("."):
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()

    if config.paths.journal.exists():
        config.paths.journal.unlink()

    print("Reset complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="filethat",
        description="Document classification pipeline",
    )

    config_default = Path(os.environ.get("FILETHAT_CONFIG", "config.yaml"))
    parser.add_argument("--config", type=Path, default=config_default, metavar="PATH")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Process files in inbox/")
    sub.add_parser("ui", help="Launch web UI")
    sub.add_parser("stats", help="Print journal summary")
    sub.add_parser("archive", help="Move library/ into timestamped archive/")

    p = sub.add_parser("delete-archive", help="Delete all archives")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    p = sub.add_parser("clean-failed", help="Delete all failed entries")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    p = sub.add_parser("reset", help="WIPE everything (double confirmation)")
    p.add_argument("--yes", action="store_true", help="Skip first confirmation")

    args = parser.parse_args()

    log_level = os.environ.get("LOG_LEVEL", "INFO")
    log_file: Path | None = None
    data_dir = Path("data")
    if data_dir.exists():
        log_file = data_dir / "filethat.log"

    setup_logging(log_level, log_file)

    config = Config.load(args.config)

    match args.command:
        case "scan":
            cmd_scan(config)
        case "ui":
            cmd_ui(config)
        case "stats":
            cmd_stats(config)
        case "archive":
            cmd_archive(config)
        case "delete-archive":
            cmd_delete_archive(config, args.yes)
        case "clean-failed":
            cmd_clean_failed(config, args.yes)
        case "reset":
            cmd_reset(config, args.yes)
