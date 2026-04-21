"""OpenAI GPT implementation of the LLMClient protocol."""

import json
import logging
import time
from typing import Any

import openai
from openai import APIError
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from filethat.llm.base import LLMClassificationError, LLMResult
from filethat.prompt import CLASSIFY_TOOL, build_user_message, load_system_prompt
from filethat.schemas import LLMClassification

logger = logging.getLogger(__name__)

# GPT-4o pricing as of 2026-04 (USD per million tokens)
_PRICE_INPUT_PER_MTOK = 2.50
_PRICE_OUTPUT_PER_MTOK = 10.0


def _compute_cost(tokens_in: int, tokens_out: int) -> float:
    """Compute OpenAI call cost in USD."""
    return (tokens_in / 1_000_000) * _PRICE_INPUT_PER_MTOK + (
        tokens_out / 1_000_000
    ) * _PRICE_OUTPUT_PER_MTOK


def _anthropic_tool_to_openai_function(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic tool definition to OpenAI function calling format.

    Anthropic: {"name": ..., "description": ..., "input_schema": {...}}
    OpenAI:    {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
    """
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


class OpenAIClient:
    """LLMClient implementation using OpenAI GPT with function calling."""

    def __init__(self, api_key: str, model: str, prompt_language: str = "fr") -> None:
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._function_def = _anthropic_tool_to_openai_function(CLASSIFY_TOOL)
        self._system_prompt = load_system_prompt(prompt_language)

    @retry(
        retry=retry_if_exception_type(APIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    def classify(self, ocr_text: str) -> LLMResult:
        """Classify a document via function calling.

        Raises:
            LLMClassificationError: If the response cannot be parsed or validated.
        """
        start = time.perf_counter()

        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": build_user_message(ocr_text)},
            ],
            tools=[self._function_def],
            tool_choice={"type": "function", "function": {"name": "classify_document"}},
        )

        duration_ms = int((time.perf_counter() - start) * 1000)
        choice = response.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None)
        if not tool_calls:
            raise LLMClassificationError(
                f"No function call in response (finish_reason={choice.finish_reason})"
            )

        raw = tool_calls[0].function.arguments
        try:
            payload = json.loads(raw)
            classification = LLMClassification.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Invalid function call payload: %s", e)
            raise LLMClassificationError(f"Invalid schema: {e}") from e

        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0

        return LLMResult(
            classification=classification,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_read=0,
            cache_write=0,
            duration_ms=duration_ms,
            cost_usd=_compute_cost(tokens_in, tokens_out),
        )
