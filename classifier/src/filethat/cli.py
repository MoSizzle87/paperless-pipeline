"""CLI entry point: `python -m filethat.cli {run,reprocess,stats}`."""

import argparse
import json
import logging
import sys
from collections import defaultdict

from filethat.classifier import DocumentClassifier
from filethat.config import settings
from filethat.llm.factory import build_llm_client
from filethat.logging_setup import setup_logging
from filethat.paperless_client import PaperlessClient
from filethat.poller import Poller
from filethat.referential import (
    CanonicalCorrespondents,
    DocumentTypeRegistry,
    ReferentialManager,
    TagRegistry,
)

logger = logging.getLogger(__name__)


def _build_stack() -> tuple[PaperlessClient, DocumentClassifier, ReferentialManager]:
    paperless = PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    )
    llm = build_llm_client(
        provider=settings.llm_provider,
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value(),
        prompt_language=settings.effective_prompt_language,
    )
    ref_dir = settings.referentials_dir
    canonical = CanonicalCorrespondents(ref_dir / "correspondents.yaml")
    doc_type_registry = DocumentTypeRegistry(
        ref_dir / "document_types.yaml",
        language=settings.language,
    )
    tag_registry = TagRegistry(
        ref_dir / "tags.yaml",
        language=settings.language,
    )
    referential = ReferentialManager(
        client=paperless,
        canonical_correspondents=canonical,
        document_type_registry=doc_type_registry,
        tag_registry=tag_registry,
        levenshtein_threshold=settings.levenshtein_threshold,
    )
    classifier = DocumentClassifier(settings, paperless, llm, referential)
    return paperless, classifier, referential


def cmd_run() -> int:
    """Start the poller loop."""
    paperless, classifier, referential = _build_stack()
    poller = Poller(settings, paperless, classifier, referential)
    poller.install_signal_handlers()
    try:
        poller.run()
    finally:
        paperless.close()
    return 0


def cmd_reprocess(tag_name: str) -> int:
    """Reprocess all documents carrying the given tag."""
    paperless, classifier, referential = _build_stack()
    try:
        tag_id = referential.tag_id(tag_name)
        docs = paperless.list_documents_with_tag(tag_id)
        logger.info("%d document(s) to reprocess (tag=%s)", len(docs), tag_name)
        for doc in docs:
            paperless.remove_tag(doc.id, tag_id)
            classifier.classify_document(doc)
    finally:
        paperless.close()
    return 0


def cmd_stats() -> int:
    """Print classification statistics from the JSONL log."""
    log_file = settings.log_dir / "pipeline.jsonl"
    if not log_file.exists():
        print("No JSONL log found (no documents processed yet).")
        return 0

    total = 0
    by_status: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    total_cost = 0.0
    correspondents_created = 0
    confidences: list[float] = []

    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        total += 1
        by_status[entry.get("status", "unknown")] += 1
        if entry.get("document_type"):
            by_type[entry["document_type"]] += 1
        if entry.get("cost_usd"):
            total_cost += entry["cost_usd"]
        if entry.get("confidence") is not None:
            confidences.append(entry["confidence"])
        if entry.get("correspondent_created"):
            correspondents_created += 1

    print(f"\nStats\n{'=' * 40}")
    print(f"Total documents processed: {total}")
    print("\nBy status:")
    for status, count in sorted(by_status.items()):
        print(f"  {status:12s} : {count}")
    print(f"\nCorrespondents created (Class B or canonical): {correspondents_created}")
    print(f"Cumulative API cost: ${total_cost:.4f}")
    if confidences:
        avg = sum(confidences) / len(confidences)
        print(f"Average confidence: {avg:.3f}")
    print("\nTop 10 document types:")
    for doc_type, count in sorted(by_type.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count:4d}  {doc_type}")

    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging(settings.log_level, settings.log_dir)

    parser = argparse.ArgumentParser(prog="filethat")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Start the poller loop")

    p_reprocess = sub.add_parser("reprocess", help="Reprocess documents with a given tag")
    p_reprocess.add_argument("--tag", required=True, help="Tag name (e.g. ai:a-verifier)")

    sub.add_parser("stats", help="Print statistics from the JSONL log")

    args = parser.parse_args(argv)

    if args.command == "run":
        return cmd_run()
    if args.command == "reprocess":
        return cmd_reprocess(args.tag)
    if args.command == "stats":
        return cmd_stats()
    return 1


if __name__ == "__main__":
    sys.exit(main())
