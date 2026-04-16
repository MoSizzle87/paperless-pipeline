"""Orchestration : un document Paperless → LLM → validation → push."""

import logging
import time
from datetime import datetime

from pipeline.config import Settings
from pipeline.llm_client import LLMClassificationError, LLMClient
from pipeline.logging_setup import log_classification
from pipeline.paperless_client import PaperlessClient
from pipeline.referential import ReferentialManager
from pipeline.schemas import ClassificationResult, PaperlessDocument

logger = logging.getLogger(__name__)

TAG_PROCESSED = "ai:processed"
TAG_REVIEW = "ai:a-verifier"
TAG_FAILED = "ai:failed"


class DocumentClassifier:
    """Orchestrateur du traitement d'un document unique."""

    def __init__(
        self,
        settings: Settings,
        paperless: PaperlessClient,
        llm: LLMClient,
        referential: ReferentialManager,
    ):
        self._settings = settings
        self._paperless = paperless
        self._llm = llm
        self._ref = referential

    def classify_document(self, doc: PaperlessDocument) -> ClassificationResult:
        """Traite un document complet. Ne lève jamais — encapsule tout dans le résultat."""
        start = time.perf_counter()
        log = logger.getChild(f"doc[{doc.id}]")

        # Récupère le contenu OCR (peut être None si Paperless n'a pas fini l'OCR)
        if not doc.content or len(doc.content.strip()) < 50:
            log.warning("Contenu OCR absent ou trop court, skip")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error="OCR content missing or too short",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        # Appel LLM
        try:
            llm_result = self._llm.classify(doc.content)
        except LLMClassificationError as e:
            log.error("Classification échouée : %s", e)
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=str(e),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:  # noqa: BLE001 — on loggue et on taggue failed
            log.exception("Erreur inattendue lors de l'appel LLM")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=f"Unexpected: {e}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        cls = llm_result.classification

        # Résolution des entités vers des IDs Paperless
        try:
            correspondent_id, was_created = self._ref.resolve_correspondent(cls.correspondent)
            document_type_id = self._ref.resolve_document_type(cls.document_type)
            tag_ids = self._ref.resolve_tags(cls.tags)
        except Exception as e:  # noqa: BLE001
            log.exception("Résolution référentielle échouée")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=f"Referential resolution: {e}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        # Construction du patch Paperless
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
            # Paperless accepte date ISO pour le champ `created_date`
            payload["created_date"] = cls.created.isoformat()

        try:
            self._paperless.patch_document(doc.id, payload)
        except Exception as e:  # noqa: BLE001
            log.exception("Patch Paperless échoué")
            self._tag_failed(doc.id)
            return ClassificationResult(
                doc_id=doc.id,
                status="failed",
                error=f"Paperless patch: {e}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "Classifié %s → %s / %s (conf=%.2f, %dms, $%.4f)",
            cls.title,
            cls.document_type,
            cls.correspondent,
            cls.confidence,
            duration_ms,
            llm_result.cost_usd,
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
            cost_usd=round(llm_result.cost_usd, 6),
            duration_ms=duration_ms,
        )
        log_classification(result)
        return result

    def _tag_failed(self, doc_id: int) -> None:
        try:
            self._paperless.add_tag(doc_id, self._ref.tag_id(TAG_FAILED))
        except Exception:  # noqa: BLE001
            logger.exception("Impossible de taguer doc %s comme failed", doc_id)
