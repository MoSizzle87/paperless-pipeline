"""Base types and protocol for LLM provider abstraction."""

from typing import Protocol, runtime_checkable


class LLMResult:
    """Result of a single LLM classification call with usage metadata.

    Token counters are provider-agnostic. Providers that do not support
    prompt caching should pass 0 for cache_read and cache_write.

    For Anthropic, the three input counters are disjoint:
    - tokens_in        : fresh tokens billed at standard rate
    - cache_read       : tokens served from cache (reduced rate)
    - cache_write      : tokens written to cache (higher rate)

    For OpenAI and others, only tokens_in and tokens_out are used.
    """

    def __init__(
        self,
        classification: "LLMClassification",  # noqa: F821 — imported at runtime
        tokens_in: int,
        tokens_out: int,
        cache_read: int = 0,
        cache_write: int = 0,
        duration_ms: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        self.classification = classification
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cache_read = cache_read
        self.cache_write = cache_write
        self.duration_ms = duration_ms
        self._cost_usd = cost_usd

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens consumed across all billing categories."""
        return self.tokens_in + self.cache_read + self.cache_write

    @property
    def cost_usd(self) -> float | None:
        """Call cost in USD, or None if the provider did not compute it."""
        return self._cost_usd


class LLMClassificationError(Exception):
    """Raised when LLM output cannot be parsed or validated."""


@runtime_checkable
class LLMClient(Protocol):
    """Protocol that every LLM provider implementation must satisfy."""

    def classify(self, ocr_text: str) -> LLMResult:
        """Classify a document from its OCR text.

        Args:
            ocr_text: Raw OCR output of the document.

        Returns:
            LLMResult with structured classification and usage metadata.

        Raises:
            LLMClassificationError: If the response cannot be parsed or validated.
        """
        ...
