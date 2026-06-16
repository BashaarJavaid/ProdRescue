"""Central configuration — single source of truth for all env-driven settings.

Imported by the API, agents, MCP servers and scripts so that values like the
embedding dimension are defined exactly once (it must match the VECTOR(n)
column in infra/db/init.sql).
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database / messaging
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/prodrescue"
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672//")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # LLM (OpenAI-compatible; default = Xiaomi MiMo-V2.5-Pro)
    llm_base_url: str = Field(default="http://localhost:8080/v1")
    llm_api_key: str = Field(default="changeme")
    llm_model: str = Field(default="MiMo-V2.5-Pro")

    # Embeddings
    embed_backend: str = Field(default="sentence-transformers")  # or "hash"
    embed_model: str = Field(default="BAAI/bge-small-en-v1.5")
    embed_dim: int = Field(default=384)

    # GitHub
    github_token: str = Field(default="")
    repo_full_name: str = Field(default="youruser/prodrescue-sample-target")
    # Local checkout of the target repo (used by dry-run get_file_contents and the harness).
    target_repo_dir: str = Field(default="sample_target")

    # MCP servers
    harness_mcp_url: str = Field(default="http://localhost:8001/mcp")
    logs_db_mcp_url: str = Field(default="http://localhost:8002/mcp")

    # Observability
    langsmith_api_key: str = Field(default="")
    langsmith_project: str = Field(default="prodrescue")
    worker_metrics_port: int = Field(default=9100)

    @property
    def psycopg_dsn(self) -> str:
        """LangGraph's PostgresSaver expects a psycopg-style DSN."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Convenience module-level singleton.
settings = get_settings()

# Allow tests / scripts to force the lightweight embedding backend.
if os.getenv("EMBED_BACKEND") == "hash":
    settings.embed_backend = "hash"
