"""User-editable trading settings persisted in trading.db.

All risk limits and cost assumptions are configurable. Cost defaults are deliberately
conservative PLACEHOLDERS — verify them against Vested's current pricing page and your bank.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from sqlalchemy.engine import Engine

from tradingos.db.models import Setting
from tradingos.db.session import session_scope

SETTINGS_KEY = "trading_settings_v1"


@dataclass
class TradingSettings:
    # ---- capital & risk (Module 7) ----
    starting_capital_usd: float = 300.0
    risk_per_trade_pct: float = 1.0          # % of equity risked per trade
    max_open_risk_pct: float = 2.0           # aggregate open risk cap, % of equity
    max_positions: int = 3
    share_increment: float = 1.0             # 1 = whole shares; 0.01 etc. if your broker allows fractional
    min_reward_risk: float = 2.0             # minimum R:R to call a plan eligible
    max_trades_per_month: int = 6            # overtrading flag threshold
    allow_averaging_down: bool = False       # informational; the app never suggests it

    # ---- costs (verify on Vested's pricing page!) ----
    commission_per_order_usd: float = 0.0
    commission_pct: float = 0.0              # % of order value
    commission_min_usd: float = 0.0
    spread_bps: float = 5.0                  # assumed half-spread paid per side (basis points)
    slippage_bps: float = 5.0                # assumed slippage per side (basis points)
    fx_markup_pct: float = 1.0               # INR↔USD conversion markup, applied to deposits/withdrawals
    include_fx_in_trade_costs: bool = False  # if True, amortise a round-trip FX cost into each trade estimate
    est_tax_rate_pct: float = 30.0           # estimated tax on short-term gains (India: slab rate). Estimate only.

    # ---- scanner (Module 2) ----
    min_price: float = 5.0
    min_avg_dollar_volume_m: float = 20.0    # $ millions, 20-day average
    rsi_min: float = 45.0
    rsi_max: float = 75.0
    rel_volume_breakout: float = 1.5
    rel_volume_unusual: float = 2.0
    breakout_lookback: int = 55
    rs_lookback_days: int = 63
    earnings_warning_days: int = 14
    require_above_200dma: bool = True

    # ---- analytics ----
    min_sample_for_conclusions: int = 20

    # ---- misc ----
    news_max_age_days: int = 7
    extra_tickers: list[str] = field(default_factory=list)

    # ---- alert notifications (push / webhook) ----
    alert_ntfy_topic: str = ""
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    alert_webhook_url: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "TradingSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def validate(self) -> list[str]:
        errs = []
        if self.starting_capital_usd <= 0:
            errs.append("Starting capital must be positive.")
        if not 0 < self.risk_per_trade_pct <= 5:
            errs.append("Risk per trade must be between 0 and 5%.")
        if self.max_open_risk_pct < self.risk_per_trade_pct:
            errs.append("Max open risk must be ≥ risk per trade.")
        if self.max_open_risk_pct > 10:
            errs.append("Max open risk above 10% is not allowed.")
        if self.max_positions < 1:
            errs.append("Max positions must be ≥ 1.")
        if not 0 < self.share_increment <= 1:
            errs.append("Share increment must be in (0, 1].")
        if self.min_reward_risk < 1:
            errs.append("Minimum reward:risk must be ≥ 1.")
        for n in ("commission_per_order_usd", "commission_pct", "commission_min_usd", "spread_bps",
                  "slippage_bps", "fx_markup_pct", "est_tax_rate_pct"):
            if getattr(self, n) < 0:
                errs.append(f"{n} cannot be negative.")
        if self.rsi_min >= self.rsi_max:
            errs.append("RSI min must be below RSI max.")
        return errs


def load_settings(engine: Engine | None = None) -> TradingSettings:
    with session_scope(engine) as s:
        row = s.get(Setting, SETTINGS_KEY)
        if row is None:
            return TradingSettings()
        return TradingSettings.from_dict(json.loads(row.value_json))


def save_settings(settings: TradingSettings, engine: Engine | None = None) -> None:
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
