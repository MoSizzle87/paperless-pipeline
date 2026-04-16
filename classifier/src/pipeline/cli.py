"""Point d'entrée CLI : `python -m pipeline.cli {run,reprocess,stats}`."""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from pipeline.classifier import DocumentClassifier
from pipeline.config import settings
from pipeline.llm_client import LLMClient
from pipeline.logging_setup import setup_logging
from pipeline.paperless_client import PaperlessClient
from pipeline.poller import Poller
from pipeline.referential import CanonicalCorrespondents, ReferentialManager

logger = logging.getLogger(__name__)


def _build_stack() -> tuple[PaperlessClient, DocumentClassifier, ReferentialManager]:
    paperless = PaperlessClient(
        base_url=str(settings.paperless_api_url),
        token=settings.paperless_api_token.get_secret_value(),
    )
    llm = LLMClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
    )
    canonical = CanonicalCorrespondents(settings.referentials_dir / "correspondents_canonical.yaml")
    referential = ReferentialManager(
        client=paperless,
        canonical_correspondents=canonical,
        levenshtein_threshold=settings.levenshtein_threshold,
    )
    classifier = DocumentClassifier(settings, paperless, llm, referential)
    return paperless, classifier, referential


def cmd_run() -> int:
    """Démarre le poller en boucle."""
    paperless, classifier, referential = _build_stack()
    poller = Poller(settings, paperless, classifier, referential)
    poller.install_signal_handlers()
    try:
        poller.run()
    finally:
        paperless.close()
    return 0


def cmd_reprocess(tag_name: str) -> int:
    """Retraite les documents ayant le tag donné (ex: ai:a-verifier, ai:failed)."""
    paperless, classifier, referential = _build_stack()
    try:
        tag_id = referential.tag_id(tag_name)
        docs = paperless.list_documents_with_tag(tag_id)
        logger.info("%d document(s) à retraiter (tag=%s)", len(docs), tag_name)
        for doc in docs:
            # On retire le tag avant reprocess pour ne pas bloquer la re-catégorisation
            paperless.remove_tag(doc.id, tag_id)
            classifier.classify_document(doc)
    finally:
        paperless.close()
    return 0


def cmd_stats() -> int:
    """Résumé des classifications depuis le JSONL."""
    log_file = settings.log_dir / "pipeline.jsonl"
    if not log_file.exists():
        print("Aucun log JSONL trouvé (pas encore de docs traités).")
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

    print(f"\n📊 Stats pipeline\n{'=' * 40}")
    print(f"Total documents traités : {total}")
    print("\nPar statut :")
    for status, count in sorted(by_status.items()):
        print(f"  {status:12s} : {count}")
    print(f"\nCorrespondants créés (Classe B ou canoniques) : {correspondents_created}")
    print(f"Coût cumulé API : ${total_cost:.4f}")
    if confidences:
        avg = sum(confidences) / len(confidences)
        print(f"Confidence moyenne : {avg:.3f}")
    print("\nTop 10 types de documents :")
    for doc_type, count in sorted(by_type.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count:4d}  {doc_type}")

    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging(settings.log_level, settings.log_dir)

    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Démarre le poller en boucle")

    p_reprocess = sub.add_parser("reprocess", help="Retraite les docs d'un tag donné")
    p_reprocess.add_argument("--tag", required=True, help="Nom du tag (ex: ai:a-verifier)")

    sub.add_parser("stats", help="Statistiques depuis le JSONL")

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
