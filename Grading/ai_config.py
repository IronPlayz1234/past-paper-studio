"""AI configuration for Groq grading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv

    # Load only the per-user settings file below; never search the working directory.
except ImportError:
    pass


DEFAULT_GROQ_TEXT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DEFAULT_GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DEFAULT_AI_TIMEOUT = 120
DEFAULT_AI_MAX_TOKENS = 1000
STRICT_AI_TEMPERATURE = 0.0


def _env_path() -> str:
    from Core.runtime_paths import settings_env_path, migrate_legacy_data
    migrate_legacy_data()
    return settings_env_path()


def _clean_env_value(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and (
        (text.startswith('"') and text.endswith('"'))
        or (text.startswith("'") and text.endswith("'"))
    ):
        text = text[1:-1].strip()
    return text


@dataclass
class AIConfig:
    """Configuration for Groq grading."""

    api_key: str = ""
    text_model: str = DEFAULT_GROQ_TEXT_MODEL
    vision_model: str = DEFAULT_GROQ_VISION_MODEL
    timeout: int = DEFAULT_AI_TIMEOUT
    max_tokens: int = DEFAULT_AI_MAX_TOKENS
    temperature: float = STRICT_AI_TEMPERATURE

    @classmethod
    def load_from_env(cls) -> "AIConfig":
        try:
            load_dotenv(_env_path(), override=True)  # type: ignore[misc]
        except Exception:
            pass

        timeout_raw = os.environ.get("AI_TIMEOUT", str(DEFAULT_AI_TIMEOUT))
        max_tokens_raw = os.environ.get("AI_MAX_TOKENS", str(DEFAULT_AI_MAX_TOKENS))
        try:
            timeout = int(timeout_raw)
        except Exception:
            timeout = DEFAULT_AI_TIMEOUT
        try:
            max_tokens = int(max_tokens_raw)
        except Exception:
            max_tokens = DEFAULT_AI_MAX_TOKENS

        return cls(
            api_key=_clean_env_value(str(os.environ.get("GROQ_API_KEY", "") or "")),
            text_model=_clean_env_value(str(os.environ.get("GROQ_TEXT_MODEL", DEFAULT_GROQ_TEXT_MODEL) or ""))
            or DEFAULT_GROQ_TEXT_MODEL,
            vision_model=_clean_env_value(str(os.environ.get("GROQ_VISION_MODEL", DEFAULT_GROQ_VISION_MODEL) or ""))
            or DEFAULT_GROQ_VISION_MODEL,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=STRICT_AI_TEMPERATURE,
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        if not str(self.api_key or "").strip():
            return False, "GROQ_API_KEY cannot be empty"

        if not str(self.text_model or "").strip():
            return False, "GROQ_TEXT_MODEL cannot be empty"

        if not str(self.vision_model or "").strip():
            return False, "GROQ_VISION_MODEL cannot be empty"

        if self.timeout < 1:
            return False, "AI_TIMEOUT must be at least 1 second"

        if self.max_tokens < 100:
            return False, "AI_MAX_TOKENS must be at least 100"

        if abs(float(self.temperature) - STRICT_AI_TEMPERATURE) > 1e-9:
            return False, f"AI temperature is fixed at {STRICT_AI_TEMPERATURE}"

        return True, None

    @property
    def is_configured(self) -> bool:
        ok, _ = self.validate()
        return ok

    @property
    def model(self) -> str:
        """Backward-compatible alias used in existing logging paths."""
        return self.text_model

    @property
    def provider(self) -> str:
        """Backward-compatible alias for callers that still label a provider."""
        return "groq"

    @property
    def base_url(self) -> str:
        return "https://api.groq.com/openai/v1"


def get_supported_providers() -> List[str]:
    """Backward-compatible shim for legacy GUI code."""
    return ["groq"]


def get_provider_spec(provider: str) -> Dict[str, Optional[str]]:
    """Backward-compatible shim for legacy display labels."""
    _ = provider
    return {
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_TEXT_MODEL",
        "default_model": DEFAULT_GROQ_TEXT_MODEL,
        "base_url": "https://api.groq.com/openai/v1",
        "display_name": "Groq",
    }


# Default configuration instance (lazy loaded)
_default_config: Optional[AIConfig] = None


def get_ai_config() -> AIConfig:
    global _default_config
    if _default_config is None:
        _default_config = AIConfig.load_from_env()
    return _default_config


def get_ai_provider_chain() -> List[AIConfig]:
    """Backward-compatible shim that returns one Groq runtime."""
    cfg = get_ai_config()
    return [cfg] if cfg.validate()[0] else []


def is_ai_enabled() -> bool:
    return get_ai_config().is_configured


def load_ai_config() -> AIConfig:
    """Backward-compatible alias used by existing grading modules."""
    return get_ai_config()
