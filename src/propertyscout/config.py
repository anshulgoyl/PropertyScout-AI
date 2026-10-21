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
