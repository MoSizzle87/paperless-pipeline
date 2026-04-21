"""Central configuration, loaded from environment variables."""

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, populated from Docker Compose environment variables."""

    model_config = SettingsConfigDict(
        env_file=None,  # variables are injected by Docker Compose, not from .env
        case_sensitive=True,
        extra="ignore",
    )

    # Paperless-ngx
    paperless_api_url: HttpUrl = Field(alias="PAPERLESS_API_URL")
    paperless_api_token: SecretStr = Field(alias="PAPERLESS_API_TOKEN")

    # LLM provider
    llm_provider: str = Field(alias="LLM_PROVIDER", default="anthropic")
    llm_model: str = Field(alias="LLM_MODEL", default="claude-sonnet-4-6")
    llm_api_key: SecretStr = Field(alias="LLM_API_KEY")

    # Language
    language: str = Field(alias="LANGUAGE", default="fr")
    prompt_language: str | None = Field(alias="PROMPT_LANGUAGE", default=None)
    export_language: str | None = Field(alias="EXPORT_LANGUAGE", default=None)

    @property
    def effective_prompt_language(self) -> str:
        return self.prompt_language or self.language

    @property
    def effective_export_language(self) -> str:
        return self.export_language or self.language

    # Pipeline
    poll_interval_seconds: int = Field(alias="POLL_INTERVAL_SECONDS", default=60)
    confidence_threshold: float = Field(alias="CONFIDENCE_THRESHOLD", default=0.7)
    levenshtein_threshold: float = Field(alias="LEVENSHTEIN_THRESHOLD", default=0.85)

    # Referentials (YAML files mounted read-only in the container)
    referentials_dir: Path = Field(alias="REFERENTIALS_DIR", default=Path("/app/config/fr-admin"))

    # Logging
    log_level: str = Field(alias="LOG_LEVEL", default="INFO")
    log_dir: Path = Field(alias="LOG_DIR", default=Path("/app/logs"))


settings = Settings()  # type: ignore[call-arg]
