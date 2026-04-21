from filethat.llm.anthropic_client import AnthropicClient
from filethat.llm.base import LLMClient
from filethat.llm.openai_client import OpenAIClient


class UnsupportedProviderError(ValueError):
    """Raised when the requested LLM provider is not supported."""


def build_llm_client(
    provider: str,
    model: str,
    api_key: str,
    prompt_language: str = "fr",
) -> LLMClient:
    """Instantiate the appropriate LLMClient for the given provider.

    Args:
        provider:        One of "anthropic", "openai".
        model:           Model identifier.
        api_key:         API key for the provider.
        prompt_language: Language code for the system prompt (default: "fr").

    Returns:
        A concrete LLMClient instance.

    Raises:
        UnsupportedProviderError: If the provider is not supported.
    """
    match provider.lower():
        case "anthropic":
            return AnthropicClient(api_key=api_key, model=model, prompt_language=prompt_language)
        case "openai":
            return OpenAIClient(api_key=api_key, model=model, prompt_language=prompt_language)
        case _:
            supported = ", ".join(["anthropic", "openai"])
            raise UnsupportedProviderError(
                f"Unsupported provider '{provider}'. Supported: {supported}"
            )
