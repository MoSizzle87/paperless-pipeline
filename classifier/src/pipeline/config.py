"""Configuration centrale du pipeline, chargée depuis les variables d'environnement."""

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration runtime, peuplée par les variables d'environnement Docker."""

    model_config = SettingsConfigDict(
        env_file=None,  # les variables sont injectées par Docker Compose, pas par .env
        case_sensitive=True,
        extra="ignore",
    )

    # Paperless-ngx
    paperless_api_url: HttpUrl = Field(alias="PAPERLESS_API_URL")
    paperless_api_token: SecretStr = Field(alias="PAPERLESS_API_TOKEN")

    # Anthropic
    anthropic_api_key: SecretStr = Field(alias="ANTHROPIC_API_KEY")
    llm_model: str = Field(alias="LLM_MODEL", default="claude-sonnet-4-6")

    # Pipeline
    poll_interval_seconds: int = Field(alias="POLL_INTERVAL_SECONDS", default=60)
    confidence_threshold: float = Field(alias="CONFIDENCE_THRESHOLD", default=0.7)
    levenshtein_threshold: float = Field(alias="LEVENSHTEIN_THRESHOLD", default=0.85)

    # Référentiels (fichiers YAML montés en read-only dans le container)
    referentials_dir: Path = Field(alias="REFERENTIALS_DIR", default=Path("/app/referentials"))

    # Logging
    log_level: str = Field(alias="LOG_LEVEL", default="INFO")
    log_dir: Path = Field(alias="LOG_DIR", default=Path("/app/logs"))


settings = Settings()  # type: ignore[call-arg]
