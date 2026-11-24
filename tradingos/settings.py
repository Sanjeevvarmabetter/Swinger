"""User-editable app settings persisted in the database (Settings page).

Only research/analysis parameters remain; trading risk, cost and alert fields were removed with the trading modules.
Old stored settings JSON is still readable: unknown keys are ignored.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from sqlalchemy.engine import Engine

from tradingos.db.models import Setting
from tradingos.db.session import session_scope

SETTINGS_KEY = "trading_settings_v1"   # key kept so previously saved values still load


@dataclass
class AppSettings:
    # ---- technical snapshot used by company research (AI Research Chat) ----
    breakout_lookback: int = 55
    rs_lookback_days: int = 63
    rel_volume_breakout: float = 1.5
    # ---- news ----
    news_max_age_days: int = 7
    # ---- extra symbols added to the US breadth universe ----
    extra_tickers: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "AppSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def validate(self) -> list[str]:
        errs = []
        if not 5 <= self.breakout_lookback <= 260:
            errs.append("Breakout lookback must be between 5 and 260 days.")
        if not 5 <= self.rs_lookback_days <= 260:
            errs.append("Relative-strength lookback must be between 5 and 260 days.")
        if self.rel_volume_breakout <= 0:
            errs.append("Relative volume threshold must be positive.")
        if not 1 <= self.news_max_age_days <= 60:
            errs.append("News max age must be between 1 and 60 days.")
        bad = [t for t in self.extra_tickers if not (0 < len(t) <= 12 and all(c.isalnum() or c in ".-^=" for c in t))]
        if bad:
            errs.append(f"Invalid ticker symbols: {', '.join(bad[:5])}")
        return errs


TradingSettings = AppSettings   # backward-compatible alias


def load_settings(engine: Engine | None = None) -> AppSettings:
    with session_scope(engine) as s:
        row = s.get(Setting, SETTINGS_KEY)
        if row is None:
            return AppSettings()
        return AppSettings.from_dict(json.loads(row.value_json))


def save_settings(settings: AppSettings, engine: Engine | None = None) -> None:
    errs = settings.validate()
    if errs:
        raise ValueError("; ".join(errs))
    with session_scope(engine) as s:
        row = s.get(Setting, SETTINGS_KEY)
        payload = json.dumps(asdict(settings))
        if row is None:
            s.add(Setting(key=SETTINGS_KEY, value_json=payload))
        else:
            row.value_json = payload
