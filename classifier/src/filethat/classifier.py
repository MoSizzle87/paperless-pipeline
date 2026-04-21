"""Document orchestration: Paperless document → LLM → validation → patch."""

import logging
import time

from filethat.config import Settings
from filethat.llm.base import LLMClassificationError, LLMClient
from filethat.logging_setup import log_classification
from filethat.paperless_client import PaperlessClient
from filethat.referential import ReferentialManager
from filethat.schemas import ClassificationResult, PaperlessDocument

logger = logging.getLogger(__name__)

TAG_PROCESSED = "ai:processed"
TAG_REVIEW = "ai:to-check"
TAG_FAILED = "ai:failed"


class DocumentClassifier:
    """Orchestrates the full processing pipeline for a single document."""

    def __init__(
        self,
        settings: Settings,
        paperless: PaperlessClient,
        llm: LLMClient,
        referential: ReferentialManager,
    ) -> None:
        self._settings = settings
        self._paperless = paperless
        self._llm = llm
        self._ref = referential

    def classify_document(self, doc: PaperlessDocument) -> ClassificationResult:
        """Process a document end-to-end. Never raises — all errors are captured in the result."""
        start = time.perf_counter()
        log = logger.getChild(f"doc[{doc.id}]")

        # OCR content check — may be missing if Paperless has not finished OCR yet
        if not doc.content or len(doc.content.strip()) < 50:
            log.warning("OCR content missing or too short, skipping")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error="OCR content missing or too short",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        # LLM classification
        try:
            llm_result = self._llm.classify(doc.content)
        except LLMClassificationError as e:
            log.error("Classification failed: %s", e)
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=str(e),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:
            log.exception("Unexpected error during LLM call")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=f"Unexpected: {e}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        cls = llm_result.classification

        # Resolve entities to Paperless ids
        try:
            correspondent_id, was_created = self._ref.resolve_correspondent(cls.correspondent)
            document_type_id = self._ref.resolve_document_type(cls.document_type)
            tag_ids = self._ref.resolve_tags(cls.tags)
        except Exception as e:
            log.exception("Referential resolution failed")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=f"Referential resolution: {e}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        # Build Paperless patch payload
        status: str
        if cls.confidence >= self._settings.confidence_threshold:
            status_tag_id = self._ref.tag_id(TAG_PROCESSED)
            status = "ok"
        else:
            status_tag_id = self._ref.tag_id(TAG_REVIEW)
            status = "review"

        payload: dict[str, object] = {
            "title": cls.title,
            "correspondent": correspondent_id,
            "document_type": document_type_id,
            "tags": [*tag_ids, status_tag_id],
        }
        if cls.created is not None:
            # Paperless accepts ISO date for the `created_date` field
            payload["created_date"] = cls.created.isoformat()

        try:
            self._paperless.patch_document(doc.id, payload)
        except Exception as e:
            log.exception("Paperless patch failed")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=f"Paperless patch: {e}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "Classified %s → %s / %s (conf=%.2f, %dms, $%.4f)",
            cls.title,
            cls.document_type,
            cls.correspondent,
            cls.confidence,
            duration_ms,
            llm_result.cost_usd or 0.0,
        )

        result = ClassificationResult(
            doc_id=doc.id,
            status=status,  # type: ignore[arg-type]
            confidence=cls.confidence,
            document_type=cls.document_type,
            correspondent=cls.correspondent,
            correspondent_created=was_created,
            tokens_in=llm_result.total_input_tokens,
            tokens_out=llm_result.tokens_out,
            cache_read=llm_result.cache_read,
            cache_write=llm_result.cache_write,
            cost_usd=round(llm_result.cost_usd, 6) if llm_result.cost_usd is not None else None,
            duration_ms=duration_ms,
        )
        log_classification(result)
        return result

    def _tag_failed(self, doc_id: int) -> None:
        try:
            self._paperless.add_tag(doc_id, self._ref.tag_id(TAG_FAILED))
        except Exception:
            logger.exception("Failed to tag document %s as failed", doc_id)
