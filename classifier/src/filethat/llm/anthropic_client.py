"""Anthropic Claude implementation of the LLMClient protocol."""

import logging
import time
from typing import Any

from anthropic import Anthropic, APIError
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from filethat.llm.base import LLMClassificationError, LLMResult
from filethat.prompt import CLASSIFY_TOOL, build_user_message, load_system_prompt
from filethat.schemas import LLMClassification

logger = logging.getLogger(__name__)

# Claude Sonnet 4.6 pricing as of 2026-04 (USD per million tokens)
_PRICE_INPUT_PER_MTOK = 3.0
_PRICE_OUTPUT_PER_MTOK = 15.0
_PRICE_CACHE_READ_PER_MTOK = 0.30
_PRICE_CACHE_WRITE_PER_MTOK = 3.75


def _compute_cost(
    tokens_in: int,
    tokens_out: int,
    cache_read: int,
    cache_write: int,
) -> float:
    """Compute Anthropic call cost in USD.

    The three input token counters are disjoint — no double-counting.
    """
    return (
        (tokens_in / 1_000_000) * _PRICE_INPUT_PER_MTOK
        + (cache_read / 1_000_000) * _PRICE_CACHE_READ_PER_MTOK
        + (cache_write / 1_000_000) * _PRICE_CACHE_WRITE_PER_MTOK
        + (tokens_out / 1_000_000) * _PRICE_OUTPUT_PER_MTOK
    )


class AnthropicClient:
    """LLMClient implementation using Anthropic Claude with tool use and prompt caching."""

    def __init__(self, api_key: str, model: str, prompt_language: str = "fr") -> None:
        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._system_prompt = load_system_prompt(prompt_language)

    @retry(
        retry=retry_if_exception_type(APIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    def classify(self, ocr_text: str) -> LLMResult:
        """Classify a document via tool use.

        Raises:
            LLMClassificationError: If the response cannot be parsed or validated.
        """
        start = time.perf_counter()

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
                    "text": self._system_prompt,
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

        tool_use_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if tool_use_block is None:
            raise LLMClassificationError(
                f"No tool_use block in response (stop_reason={response.stop_reason})"
            )

        try:
            classification = LLMClassification.model_validate(tool_use_block.input)
        except ValidationError as e:
            logger.warning("Invalid tool_use payload: %s", e)
            raise LLMClassificationError(f"Invalid schema: {e}") from e

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
            cost_usd=_compute_cost(
                tokens_in=usage.input_tokens,
                tokens_out=usage.output_tokens,
                cache_read=cache_read,
                cache_write=cache_write,
            ),
        )
