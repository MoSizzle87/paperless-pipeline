from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from filethat.classify import (
    ANTHROPIC_TOOL,
    OPENAI_TOOL,
    AnthropicClassifier,
    ClassificationResult,
    OpenAIClassifier,
    get_classifier,
)
from filethat.config import Config


def make_config(provider: str = "anthropic") -> Config:
    return Config.model_validate(
        {
            "llm": {
                "provider": provider,
                "model": "claude-sonnet-4-6" if provider == "anthropic" else "gpt-4o",
                "temperature": 0,
            },
            "referential": {
                "document_types": [{"key": "invoice", "fr": "Facture", "en": "Invoice"}],
                "correspondents": ["EDF"],
            },
        }
    )


MOCK_RESULT = {
    "document_type": "invoice",
    "correspondent": "EDF",
    "document_date": "2024-01-15",
    "title": "Facture janvier 2024",
    "language": "fr",
    "confidence": 0.95,
    "reasoning": "Clear EDF invoice with amount and date.",
    "new_correspondent": False,
}


# --- Anthropic ---

def _make_anthropic_response(data: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "classify_document"
    block.input = data
    response = MagicMock()
    response.content = [block]
    return response


def test_anthropic_classifier_returns_result():
    config = make_config("anthropic")
    classifier = AnthropicClassifier()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response(MOCK_RESULT)

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = classifier.classify("sample text", config)

    assert isinstance(result, ClassificationResult)
    assert result.document_type == "invoice"
    assert result.correspondent == "EDF"
    assert result.confidence == 0.95
    assert result.new_correspondent is False


def test_anthropic_uses_tool_choice():
    config = make_config("anthropic")
    classifier = AnthropicClassifier()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response(MOCK_RESULT)

    with patch("anthropic.Anthropic", return_value=mock_client):
        classifier.classify("text", config)

    kwargs = mock_client.messages.create.call_args[1]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "classify_document"}


def test_anthropic_sends_correct_tool_schema():
    config = make_config("anthropic")
    classifier = AnthropicClassifier()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response(MOCK_RESULT)

    with patch("anthropic.Anthropic", return_value=mock_client):
        classifier.classify("text", config)

    kwargs = mock_client.messages.create.call_args[1]
    assert len(kwargs["tools"]) == 1
    assert kwargs["tools"][0]["name"] == "classify_document"
    assert "input_schema" in kwargs["tools"][0]


def test_anthropic_includes_type_list_in_prompt():
    config = make_config("anthropic")
    classifier = AnthropicClassifier()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response(MOCK_RESULT)

    with patch("anthropic.Anthropic", return_value=mock_client):
        classifier.classify("some text", config)

    kwargs = mock_client.messages.create.call_args[1]
    user_content = kwargs["messages"][0]["content"]
    assert "invoice" in user_content
    assert "EDF" in user_content


def test_anthropic_retry_on_connection_error():
    import anthropic

    config = make_config("anthropic")
    classifier = AnthropicClassifier()
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=MagicMock()),
        _make_anthropic_response(MOCK_RESULT),
    ]

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = classifier.classify("text", config)

    assert mock_client.messages.create.call_count == 2
    assert result.document_type == "invoice"


def test_anthropic_retry_on_rate_limit():
    import anthropic

    config = make_config("anthropic")
    classifier = AnthropicClassifier()
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_client.messages.create.side_effect = [
        anthropic.RateLimitError(message="rate limited", response=mock_response, body={}),
        _make_anthropic_response(MOCK_RESULT),
    ]

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = classifier.classify("text", config)

    assert mock_client.messages.create.call_count == 2
    assert result.document_type == "invoice"


# --- OpenAI ---

def _make_openai_response(data: dict) -> MagicMock:
    fn_call = MagicMock()
    fn_call.function.arguments = json.dumps(data)
    message = MagicMock()
    message.tool_calls = [fn_call]
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_openai_classifier_returns_result():
    config = make_config("openai")
    classifier = OpenAIClassifier()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_response(MOCK_RESULT)

    with patch("openai.OpenAI", return_value=mock_client):
        result = classifier.classify("text", config)

    assert isinstance(result, ClassificationResult)
    assert result.document_type == "invoice"


def test_openai_uses_function_tool_choice():
    config = make_config("openai")
    classifier = OpenAIClassifier()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_response(MOCK_RESULT)

    with patch("openai.OpenAI", return_value=mock_client):
        classifier.classify("text", config)

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "classify_document"},
    }


def test_openai_sends_correct_tool_schema():
    config = make_config("openai")
    classifier = OpenAIClassifier()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_response(MOCK_RESULT)

    with patch("openai.OpenAI", return_value=mock_client):
        classifier.classify("text", config)

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert len(kwargs["tools"]) == 1
    assert kwargs["tools"][0]["function"]["name"] == "classify_document"
    assert kwargs["tools"][0]["function"]["strict"] is True


# --- factory ---

def test_get_classifier_anthropic():
    config = make_config("anthropic")
    classifier = get_classifier(config)
    assert isinstance(classifier, AnthropicClassifier)


def test_get_classifier_openai():
    config = make_config("openai")
    classifier = get_classifier(config)
    assert isinstance(classifier, OpenAIClassifier)


def test_get_classifier_unknown():
    config = Config.model_validate({"llm": {"provider": "anthropic"}})
    config.llm.provider = "unknown"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_classifier(config)
