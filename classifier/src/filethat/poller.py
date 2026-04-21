"""Main polling loop: watches Paperless-ngx and triggers document classification."""

import logging
import signal
import time
from types import FrameType

from filethat.classifier import TAG_FAILED, TAG_PROCESSED, TAG_REVIEW, DocumentClassifier
from filethat.config import Settings
from filethat.paperless_client import PaperlessClient
from filethat.referential import ReferentialManager

logger = logging.getLogger(__name__)


class Poller:
    """Polls Paperless-ngx and triggers classification for unprocessed documents."""

    def __init__(
        self,
        settings: Settings,
        paperless: PaperlessClient,
        classifier: DocumentClassifier,
        referential: ReferentialManager,
    ) -> None:
        self._settings = settings
        self._paperless = paperless
        self._classifier = classifier
        self._ref = referential
        self._stop = False

    def install_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("Signal %s received, shutting down after current iteration", signum)
        self._stop = True

    def run(self) -> None:
        """Main loop. Runs until SIGTERM or SIGINT is received."""
        logger.info(
            "Poller started (interval=%ss, conf_threshold=%.2f, model=%s)",
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
                    logger.info("%d document(s) to classify", len(docs))
                    for doc in docs:
                        if self._stop:
                            break
                        self._classifier.classify_document(doc)
                else:
                    logger.debug("No documents pending")
            except Exception:
                logger.exception("Error in poller loop, continuing")

            # Interruptible sleep
            for _ in range(self._settings.poll_interval_seconds):
                if self._stop:
                    break
                time.sleep(1)

        logger.info("Poller stopped gracefully")
