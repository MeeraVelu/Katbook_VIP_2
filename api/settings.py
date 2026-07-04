"""
api/settings.py — configuration for the API service (pydantic-settings).

Kept separate from the pipeline's :mod:`pipeline.settings`: the API is a thin,
ML-free process, so it only needs DB/Redis/auth/CORS knobs. Every value comes from
the environment; secrets are never hard-coded.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- database ------------------------------------------------------------ #
    database_url: str | None = Field(
        None, validation_alias=AliasChoices("DATABASE_URL", "database_url")
    )
    db_pool_size: int = Field(10, validation_alias=AliasChoices("DB_POOL_SIZE", "db_pool_size"))
    db_max_overflow: int = Field(
        20, validation_alias=AliasChoices("DB_MAX_OVERFLOW", "db_max_overflow")
    )
    db_statement_timeout_ms: int = Field(
        30000, validation_alias=AliasChoices("DB_STATEMENT_TIMEOUT_MS", "db_statement_timeout_ms")
    )

    # --- redis / queue ------------------------------------------------------- #
    redis_url: str = Field(
        "redis://redis:6379/0", validation_alias=AliasChoices("REDIS_URL", "redis_url")
    )
    celery_task_name: str = Field(
        "worker.tasks.process_video",
        validation_alias=AliasChoices("CELERY_TASK_NAME", "celery_task_name"),
    )

    # --- auth / CORS --------------------------------------------------------- #
    api_key: str | None = Field(None, validation_alias=AliasChoices("API_KEY", "api_key"))
    cors_origins: str = Field("*", validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"))

    # --- inbox / paths ------------------------------------------------------- #
    inbox_dir: str = Field(
        "/data/inbox", validation_alias=AliasChoices("VIDEO_INBOX_DIR", "inbox_dir")
    )

    # --- search -------------------------------------------------------------- #
    embed_model: str = Field(
        "BAAI/bge-m3", validation_alias=AliasChoices("KVIP_EMBED_MODEL", "embed_model")
    )
    embed_dim: int = Field(1024, validation_alias=AliasChoices("KVIP_EMBED_DIM", "embed_dim"))
    hnsw_ef_search: int = Field(
        80, validation_alias=AliasChoices("HNSW_EF_SEARCH", "hnsw_ef_search")
    )
    # OpenAI-compatible embeddings endpoint used ONLY to embed the search query
    # (keeps the API image ML-free). Unset -> semantic/hybrid degrade to keyword.
    embeddings_url: str | None = Field(
        None, validation_alias=AliasChoices("EMBEDDINGS_URL", "embeddings_url")
    )
    embeddings_model: str = Field(
        "BAAI/bge-m3", validation_alias=AliasChoices("EMBEDDINGS_MODEL", "embeddings_model")
    )
    embeddings_api_key: str = Field(
        "EMPTY", validation_alias=AliasChoices("EMBEDDINGS_API_KEY", "embeddings_api_key")
    )

    # --- pagination / misc --------------------------------------------------- #
    default_page_size: int = Field(
        25, validation_alias=AliasChoices("DEFAULT_PAGE_SIZE", "default_page_size")
    )
    max_page_size: int = Field(200, validation_alias=AliasChoices("MAX_PAGE_SIZE", "max_page_size"))
    require_gpu_heartbeat_for_ready: bool = Field(
        True, validation_alias=AliasChoices("READY_REQUIRES_GPU", "require_gpu_heartbeat_for_ready")
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]


_settings: APISettings | None = None


def get_api_settings() -> APISettings:
    global _settings
    if _settings is None:
        _settings = APISettings()
    return _settings
