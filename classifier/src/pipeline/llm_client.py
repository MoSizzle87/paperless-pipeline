"""Client Anthropic avec tool use, prompt caching, retry et calcul de coût."""

import logging
import time
from typing import Any

from anthropic import Anthropic, APIError
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline.prompt import CLASSIFY_TOOL, SYSTEM_PROMPT, build_user_message
from pipeline.schemas import LLMClassification

logger = logging.getLogger(__name__)

# Tarifs Claude Sonnet 4.6 au 2026-04 (USD par million de tokens)
PRICE_INPUT_PER_MTOK = 3.0
PRICE_OUTPUT_PER_MTOK = 15.0
PRICE_CACHE_READ_PER_MTOK = 0.30
PRICE_CACHE_WRITE_PER_MTOK = 3.75


class LLMResult:
    """Résultat d'un appel LLM enrichi de métadonnées.

    L'API Anthropic renvoie 3 compteurs de tokens d'input DISJOINTS :
    - input_tokens          : tokens neufs facturés au tarif plein
    - cache_read_input_tokens   : tokens lus depuis le cache (tarif réduit)
    - cache_creation_input_tokens : tokens écrits dans le cache (tarif majoré)

    Le total d'input consommé par le modèle est la somme des trois,
    mais chacun est facturé à son propre tarif.
    """

    def __init__(
        self,
        classification: LLMClassification,
        tokens_in: int,
        tokens_out: int,
        cache_read: int,
        cache_write: int,
        duration_ms: int,
    ):
        self.classification = classification
        self.tokens_in = tokens_in  # tokens neufs uniquement
        self.tokens_out = tokens_out
        self.cache_read = cache_read
        self.cache_write = cache_write
        self.duration_ms = duration_ms

    @property
    def total_input_tokens(self) -> int:
        """Somme des tokens d'input consommés, toutes catégories confondues."""
        return self.tokens_in + self.cache_read + self.cache_write

    @property
    def cost_usd(self) -> float:
        """Coût de l'appel, en USD.

        Chaque catégorie de tokens d'input est facturée à son propre tarif.
        Pas de double-comptage : les 3 compteurs sont disjoints côté API.
        """
        return (
            (self.tokens_in / 1_000_000) * PRICE_INPUT_PER_MTOK
            + (self.cache_read / 1_000_000) * PRICE_CACHE_READ_PER_MTOK
            + (self.cache_write / 1_000_000) * PRICE_CACHE_WRITE_PER_MTOK
            + (self.tokens_out / 1_000_000) * PRICE_OUTPUT_PER_MTOK
        )


class LLMClassificationError(Exception):
    """Levée quand la sortie LLM ne peut pas être parsée/validée."""


class LLMClient:
    """Wrapper Anthropic utilisant tool use pour garantir la structure de sortie."""

    def __init__(self, api_key: str, model: str):
        self._client = Anthropic(api_key=api_key)
        self._model = model

    @retry(
        retry=retry_if_exception_type(APIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    def classify(self, ocr_text: str) -> LLMResult:
        """Classifie un document via tool use. Lève LLMClassificationError si échec."""
        start = time.perf_counter()

        # Messages = few-shot examples + vrai document à classifier
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_user_message(ocr_text)},
        ]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=0.0,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[
                {
                    **CLASSIFY_TOOL,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tool_choice={"type": "tool", "name": "classify_document"},
            messages=messages,
        )

        duration_ms = int((time.perf_counter() - start) * 1000)

        # Extraction du tool_use block
        tool_use_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if tool_use_block is None:
            raise LLMClassificationError(
                f"Aucun tool_use dans la réponse (stop_reason={response.stop_reason})"
            )

        # Validation Pydantic du payload
        try:
            classification = LLMClassification.model_validate(tool_use_block.input)
        except ValidationError as e:
            logger.warning("Payload tool_use invalide : %s", e)
            raise LLMClassificationError(f"Schéma invalide : {e}") from e

        # Extraction métriques
        usage: Any = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        return LLMResult(
            classification=classification,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
            duration_ms=duration_ms,
        )
