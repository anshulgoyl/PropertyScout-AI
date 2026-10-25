"""Environment-based model configuration with no stored secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
NEBIUS_DEFAULT_MODEL = "zai-org/GLM-5.3-Flash"


def llm_enabled_from_env() -> bool:
    """Return whether API workflows should use the configured live model."""

    value = os.getenv("PROPERTYSCOUT_LLM_ENABLED", "false").strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(
        "PROPERTYSCOUT_LLM_ENABLED must be true/false, yes/no, on/off, or 1/0"
    )


def _bounded_env_int(name: str, default: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return value


def detail_fetch_limit_from_env() -> int:
    """Detail-page fetches allowed per search; 0 disables page fetching."""

    return _bounded_env_int("PROPERTYSCOUT_DETAIL_FETCH_LIMIT", default=3, maximum=10)


def search_query_limit_from_env() -> int:
    """Search API calls allowed per search, including the primary query."""

    return _bounded_env_int("PROPERTYSCOUT_SEARCH_QUERY_LIMIT", default=3, maximum=10)


def discovery_search_budget_from_env() -> int:
    """Authenticated search budget for the discovery engine (CLI default: 10)."""

    return _bounded_env_int("PROPERTYSCOUT_DISCOVERY_SEARCH_BUDGET", default=30, maximum=50)


def discovery_index_fetch_budget_from_env() -> int:
    """Keyless index-page fetches for the discovery engine (CLI default: 10)."""

    return _bounded_env_int(
        "PROPERTYSCOUT_DISCOVERY_INDEX_FETCH_BUDGET", default=30, maximum=50
    )


def discovery_detail_fetch_budget_from_env() -> int:
    """Individual listing-page fetches for discovery (default: 80)."""

    return _bounded_env_int(
        "PROPERTYSCOUT_DISCOVERY_DETAIL_FETCH_BUDGET", default=80, maximum=150
    )


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> ModelSettings:
        provider = os.getenv("PROPERTYSCOUT_LLM_PROVIDER", "nebius").casefold()
        if provider != "nebius":
            raise ValueError(f"Unsupported model provider: {provider!r}")

        api_key = os.getenv("NEBIUS_API_KEY")
        if not api_key:
            raise ValueError("NEBIUS_API_KEY is required when LLM analysis is enabled")

        return cls(
            provider=provider,
            model=os.getenv("PROPERTYSCOUT_LLM_MODEL", NEBIUS_DEFAULT_MODEL),
            base_url=os.getenv("PROPERTYSCOUT_LLM_BASE_URL", NEBIUS_BASE_URL),
            api_key=api_key,
            temperature=float(os.getenv("PROPERTYSCOUT_LLM_TEMPERATURE", "0")),
        )
