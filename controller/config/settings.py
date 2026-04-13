from typing import Literal

from pydantic import AliasChoices, Field, StrictStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the Problemologist Controller."""

    is_integration_test: bool = Field(default=False, alias="IS_INTEGRATION_TEST")

    # LLM Settings
    llm_model: StrictStr = Field(default="z-ai/glm-4.7-flash", alias="LLM_MODEL")
    openai_api_base: str | None = Field(default=None, alias="OPENAI_API_BASE")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    llm_temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")

    # Agent Settings
    max_agent_turns: int = Field(default=60, alias="MAX_AGENT_TURNS")
    require_reasoning_traces: bool = Field(
        default=False, alias="REQUIRE_REASONING_TRACES"
    )

    # Infrastructure Settings
    worker_light_url: str = Field(
        default="http://127.0.0.1:18001",
        validation_alias=AliasChoices("WORKER_LIGHT_URL", "WORKER_URL"),
    )
    worker_light_transport: Literal["auto", "http", "ws"] = Field(
        default="ws",
        validation_alias=AliasChoices("WORKER_LIGHT_TRANSPORT", "WORKER_TRANSPORT"),
    )
    worker_heavy_url: str | None = Field(
        default="http://127.0.0.1:18002", alias="WORKER_HEAVY_URL"
    )
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:15432/postgres",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )

    # Observability Settings
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()
