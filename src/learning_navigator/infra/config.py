"""Application configuration — env vars + file fallback.

Follows the 12-factor pattern: environment variables win, with a Pydantic
``BaseSettings`` model for typed access and validation.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class StorageBackend(str, Enum):
    LOCAL_JSON = "local_json"
    LOCAL_SQLITE = "local_sqlite"
    AZURE_BLOB = "azure_blob"


class SearchBackend(str, Enum):
    LOCAL_TFIDF = "local_tfidf"
    AZURE_AI_SEARCH = "azure_ai_search"


class Settings(BaseSettings):
    """Central settings object — instantiate once and inject."""

    # ── General ────────────────────────────────────────────────────────
    environment: Environment = Environment.LOCAL
    app_name: str = "learning-navigator"
    debug: bool = False
    log_level: str = "INFO"
    log_format: str = "json"  # "json" | "console"

    # ── Storage ────────────────────────────────────────────────────────
    storage_backend: StorageBackend = StorageBackend.LOCAL_JSON
    local_data_dir: Path = Path("data")

    # Azure Storage (used when storage_backend = azure_blob)
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "learning-navigator"

    # ── RAG / Search ───────────────────────────────────────────────────
    search_backend: SearchBackend = SearchBackend.LOCAL_TFIDF
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    azure_search_index: str = "learning-navigator-index"

    # ── Orchestrator tuning ────────────────────────────────────────────
    inactivity_threshold_hours: float = 48.0
    debate_enabled: bool = True
    adaptive_routing_enabled: bool = True
    max_debate_rounds: int = 2
    confidence_threshold: float = 0.6

    # ── Cost-aware routing ─────────────────────────────────────────────
    cost_budget_per_turn: float = Field(
        default=10.0,
        description="Abstract cost units available per orchestrator turn.",
    )

    model_config: dict[str, Any] = {
        "env_prefix": "LN_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton accessor — import and call ``get_settings()``.
_settings_instance: Settings | None = None


def get_settings(**overrides: Any) -> Settings:
    """Return (and cache) the global settings instance."""
    global _settings_instance
    if _settings_instance is None or overrides:
        _settings_instance = Settings(**overrides)
    return _settings_instance


def reset_settings() -> None:
    """Reset cached settings — useful in tests."""
    global _settings_instance
    _settings_instance = None
