"""Central application configuration.

Everything the app needs from the environment (API keys, model name, tracing
settings) is declared here as a single, validated object. This has three
benefits over scattering ``os.getenv(...)`` calls around the codebase:

1. **Fail fast** - if a required variable like ``GROQ_API_KEY`` is missing,
   the app refuses to start with a clear error, instead of crashing halfway
   through a request.
2. **One source of truth** - every module imports the same settings object.
3. **No accidental leaks** - secrets live on a typed object and are never
   printed to the console.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view of the environment.

    Field names are matched to environment variables case-insensitively, so the
    field ``groq_api_key`` is populated from ``GROQ_API_KEY`` in your ``.env``.
    """

    # `model_config` tells pydantic-settings where to read values from.
    # - env_file=".env": load variables from the local .env file if present.
    # - case_sensitive=False: GROQ_API_KEY matches the field groq_api_key.
    # - extra="ignore": don't error on unrelated variables in the environment.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required: the app cannot run without this ---
    groq_api_key: str = Field(
        ...,  # the "..." means REQUIRED - startup fails if it's missing
        description="API key for Groq (the LLM provider).",
    )

    # --- Optional, with sensible defaults ---
    groq_model: str = Field(
        # Override in .env with GROQ_MODEL=... . Other good options for this key:
        # openai/gpt-oss-120b (higher quality), qwen/qwen3.8-27b.
        default="openai/gpt-oss-20b",
        description="Which Groq model to use for generation (the fast default).",
    )
    groq_model_strong: str = Field(
        default="openai/gpt-oss-120b",
        description="Higher-quality model used for the main writing step.",
    )
    groq_max_tokens: int = Field(
        # Groq's free tier allows only 8000 tokens/minute (TPM), and a request
        # costs input + max_tokens. Keeping this modest lets the full
        # title -> content -> translate flow fit under the free-tier limit.
        # Raise it (e.g. 4096) via GROQ_MAX_TOKENS if you upgrade your Groq tier.
        default=1500,
        description="Max output tokens per LLM call.",
    )
    groq_reasoning_effort: str = Field(
        # gpt-oss models "reason" before answering; on 'high' that can consume
        # most of the output budget (leaving translations empty). 'low' keeps
        # reasoning tiny so tokens go to the actual text.
        default="low",
        description="Reasoning effort for gpt-oss models: low | medium | high.",
    )

    groq_timeout: float = Field(
        default=60.0,
        description="Seconds to wait for a single LLM call before giving up.",
    )

    # --- Database (Postgres + pgvector) for long-term memory ---
    database_url: str = Field(
        default="postgresql://blog:blog@localhost:5432/blog",
        description="Postgres connection string (matches docker-compose 'db' service).",
    )
    embed_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Local embedding model (fastembed) for semantic memory.",
    )

    # --- Optional: LangSmith tracing/observability ---
    langchain_api_key: str | None = Field(
        default=None,
        description="LangSmith API key. Enables tracing when set.",
    )
    langchain_project: str | None = Field(
        default=None,
        description="LangSmith project name for grouping traces.",
    )

    @field_validator("groq_api_key")
    @classmethod
    def _require_non_empty_key(cls, value: str) -> str:
        """Reject blank keys with an actionable message.

        The shipped ``.env`` contains an empty placeholder (``GROQ_API_KEY=""``);
        an empty string would otherwise pass type validation and only blow up
        later inside the Groq client. Catch it here instead.
        """
        if not value or not value.strip():
            raise ValueError(
                "GROQ_API_KEY is empty. Add your real key to the .env file "
                '(replace GROQ_API_KEY="" with GROQ_API_KEY=your_key_here).'
            )
        return value.strip()


@lru_cache
def get_settings() -> Settings:
    """Return the settings, building them only once.

    ``@lru_cache`` means the ``.env`` file is read and validated a single time;
    every later call returns the same cached object. Import this function and
    call ``get_settings()`` wherever configuration is needed.
    """
    return Settings()  # type: ignore[call-arg]  # fields are loaded from env by pydantic-settings
