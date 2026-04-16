"""Boucle principale : scrute Paperless et déclenche les classifications."""

import logging
import signal
import time
from types import FrameType

from pipeline.classifier import TAG_FAILED, TAG_PROCESSED, TAG_REVIEW, DocumentClassifier
from pipeline.config import Settings
from pipeline.paperless_client import PaperlessClient
from pipeline.referential import ReferentialManager

logger = logging.getLogger(__name__)


class Poller:
    """Scrute Paperless-ngx et déclenche la classification des nouveaux docs."""

    def __init__(
        self,
        settings: Settings,
        paperless: PaperlessClient,
        classifier: DocumentClassifier,
        referential: ReferentialManager,
    ):
        self._settings = settings
        self._paperless = paperless
        self._classifier = classifier
        self._ref = referential
        self._stop = False

    def install_signal_handlers(self) -> None:
        """SIGTERM/SIGINT → arrêt propre à la prochaine itération."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("Signal %s reçu, arrêt propre après l'itération en cours", signum)
        self._stop = True

    def run(self) -> None:
        """Boucle principale. Tourne jusqu'à réception de SIGTERM/SIGINT."""
        logger.info(
            "Poller démarré (interval=%ss, conf_threshold=%.2f, model=%s)",
            self._settings.poll_interval_seconds,
            self._settings.confidence_threshold,
            self._settings.llm_model,
        )

        processed_id = self._ref.tag_id(TAG_PROCESSED)
        review_id = self._ref.tag_id(TAG_REVIEW)
        failed_id = self._ref.tag_id(TAG_FAILED)
        excluded = [processed_id, review_id, failed_id]

        while not self._stop:
            try:
                docs = self._paperless.list_documents_without_tags(excluded)
                if docs:
                    logger.info("%d document(s) à classifier", len(docs))
                    for doc in docs:
                        if self._stop:
                            break
                        self._classifier.classify_document(doc)
                else:
                    logger.debug("Aucun document en attente")
            except Exception:  # noqa: BLE001
                logger.exception("Erreur dans la boucle du poller, on continue")

            # Sleep interruptible
            for _ in range(self._settings.poll_interval_seconds):
                if self._stop:
                    break
                time.sleep(1)

        logger.info("Poller arrêté proprement")
