"""Application configuration loaded from environment variables.

Phase 0 requires no API keys. Settings are read once from the process
environment (optionally populated from a local ``.env`` file).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    app_name: str
    debug: bool
    research_culture: str = "Marwari"
    research_dialect: str = ""
    research_region: str = "Marwar / Jodhpur"
    research_setting: str = "Rural"
    research_script: str = "Devanagari"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from the environment (cached after first call)."""
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "Cultural Screenplay & Visual Adaptation Studio"),
        debug=_env_bool("DEBUG", False),
        research_culture=os.getenv("RESEARCH_CULTURE", "Marwari"),
        research_dialect=os.getenv("RESEARCH_DIALECT", ""),
        research_region=os.getenv("RESEARCH_REGION", "Marwar / Jodhpur"),
        research_setting=os.getenv("RESEARCH_SETTING", "Rural"),
        research_script=os.getenv("RESEARCH_SCRIPT", "Devanagari"),
    )
