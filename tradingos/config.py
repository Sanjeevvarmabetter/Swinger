"""Application configuration.

Secrets come ONLY from environment variables (.env). User-tunable trading settings
live in the database (see tradingos.settings) so they can be edited in the UI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val and val.strip():
        return val.strip()
    try:
        import streamlit as st
        if hasattr(st, "secrets") and name in st.secrets:
            s_val = str(st.secrets[name])
            if s_val.strip():
                return s_val.strip()
    except Exception:
        pass
    return default


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    gemini_api_key: str
    gemini_model: str
    gemini_min_interval: float
    gemini_max_retries: int
    sec_user_agent: str
    fred_api_key: str
    finnhub_api_key: str = ""
    fmp_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    ai_provider: str = "auto"

    @property
    def trading_db_path(self) -> Path:
        return self.data_dir / "trading.db"

    @property
    def longterm_db_path(self) -> Path:
        # Physically separate database: long-term holdings can never leak into trading equity.
        return self.data_dir / "longterm.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def ai_configured(self) -> bool:
        return self.groq_configured or self.gemini_configured or self.anthropic_configured

    @property
    def finnhub_configured(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def fmp_configured(self) -> bool:
        return bool(self.fmp_api_key)

    @property
    def fred_configured(self) -> bool:
        return bool(self.fred_api_key)


def load_config() -> AppConfig:
    data_dir = Path(_env("TRADINGOS_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser()
    cfg = AppConfig(
        data_dir=data_dir,
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_min_interval=float(_env("GEMINI_MIN_INTERVAL_SECONDS", "4")),
        gemini_max_retries=int(_env("GEMINI_MAX_RETRIES", "3")),
        sec_user_agent=_env("SEC_USER_AGENT"),
        fred_api_key=_env("FRED_API_KEY"),
        finnhub_api_key=_env("FINNHUB_API_KEY"),
        fmp_api_key=_env("FMP_API_KEY"),
        groq_api_key=_env("GROQ_API_KEY"),
        groq_model=_env("GROQ_MODEL", "openai/gpt-oss-120b"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        ai_provider=_env("AI_PROVIDER", "auto"),
    )
    for d in (cfg.data_dir, cfg.cache_dir, cfg.backup_dir, cfg.reports_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
