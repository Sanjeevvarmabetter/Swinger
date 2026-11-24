"""Risk-management engine (Module 7). Deterministic; no I/O; fully unit-tested.

Long-only, no leverage, no averaging down. Every proposed trade is reviewed independently
and receives a list of explicit checks + a verdict:
    Plan eligible | Wait | Watch | Avoid
The engine NEVER suggests increasing risk to participate in a trade.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from tradingos.settings import TradingSettings

EPS = 1e-9
VERDICTS = ("Plan eligible", "Wait", "Watch", "Avoid")


def floor_to_increment(x: float, inc: float) -> float:
    if x <= 0:
        return 0.0
    n = math.floor(x / inc + EPS)
    return round(n * inc, 6)


def order_commission(order_value: float, cfg: TradingSettings) -> float:
    if order_value <= 0:
        return 0.0
    c = cfg.commission_per_order_usd + order_value * cfg.commission_pct / 100
    return max(c, cfg.commission_min_usd)


def round_trip_costs(entry: float, exit_price: float, shares: float, cfg: TradingSettings) -> dict:
    """Estimated costs to enter at `entry` and exit at `exit_price` (USD)."""
    buy_val, sell_val = entry * shares, exit_price * shares
    comm = order_commission(buy_val, cfg) + order_commission(sell_val, cfg)
    spread = (buy_val + sell_val) * cfg.spread_bps / 10_000
    slip = (buy_val + sell_val) * cfg.slippage_bps / 10_000
    fx = (buy_val + sell_val) * cfg.fx_markup_pct / 100 if cfg.include_fx_in_trade_costs else 0.0
    total = comm + spread + slip + fx
    return {"commission": round(comm, 4), "spread": round(spread, 4), "slippage": round(slip, 4),
            "fx": round(fx, 4), "total": round(total, 4)}


@dataclass
class PositionSize:
    risk_budget: float
    risk_per_share: float
    raw_shares: float
    shares: float
    position_value: float
    planned_loss_gross: float
    limited_by: str            # "risk" | "cash" | "unsuitable" | "invalid"
    unsuitable: bool
    message: str = ""


def position_size(equity: float, risk_pct: float, entry: float, stop: float, share_increment: float = 1.0,
                  cash_available: float | None = None) -> PositionSize:
    """shares = floor(risk_budget / |entry − stop|), floored to share_increment and capped by cash."""
    if equity <= 0 or entry <= 0 or stop <= 0 or risk_pct <= 0:
        return PositionSize(0, 0, 0, 0, 0, 0, "invalid", True, "Equity, entry, stop and risk % must be positive.")
    budget = equity * risk_pct / 100
    rps = abs(entry - stop)
    if rps < EPS:
        return PositionSize(budget, 0, 0, 0, 0, 0, "invalid", True, "Entry and stop cannot be equal.")
    raw = budget / rps
    shares = floor_to_increment(raw, share_increment)
    limited = "risk"
    if shares <= 0:
        return PositionSize(round(budget, 4), round(rps, 4), round(raw, 6), 0.0, 0.0, 0.0, "unsuitable", True,
                            f"Risk for one unit ({share_increment:g} share) = ${rps * share_increment:.2f} exceeds "
                            f"risk budget ${budget:.2f}. Trade is unsuitable for the configured risk limit "
                            "(do not raise risk to participate).")
    if cash_available is not None:
        max_cash_shares = floor_to_increment(cash_available / entry, share_increment)
        if max_cash_shares < shares:
            shares, limited = max_cash_shares, "cash"
    if shares <= 0:
        return PositionSize(round(budget, 4), round(rps, 4), round(raw, 6), 0.0, 0.0, 0.0, "cash", True,
                            "Not enough available cash for one unit (no leverage).")
    msg = "Sized by risk budget." if limited == "risk" else "Capped by available cash (no leverage)."
    return PositionSize(round(budget, 4), round(rps, 4), round(raw, 6), shares, round(shares * entry, 2),
                        round(shares * rps, 2), limited, False, msg)


def reward_risk(entry: float, stop: float, target: float | None) -> float | None:
    if target is None or abs(entry - stop) < EPS:
        return None
    return (target - entry) / (entry - stop)


@dataclass
class OpenPositionRisk:
    ticker: str
    qty: float
    avg_entry: float
    stop: float
    sector: str = ""

    @property
    def risk(self) -> float:
        """Capital still at risk if the stop is hit (0 once the stop is at/above entry)."""
        return max(0.0, (self.avg_entry - self.stop) * self.qty)

    @property
    def value(self) -> float:
        return self.avg_entry * self.qty


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    severity: str = "hard"   # hard → Avoid, soft → Wait, info → Watch (only if failed)

    def __post_init__(self):
        self.passed = bool(self.passed)  # normalise numpy bools (JSON-safe)


@dataclass
class TradeEvaluation:
    ticker: str
    entry: float
    stop: float
    target1: float | None
    target2: float | None
    size: PositionSize
    costs_at_stop: dict
    costs_at_t1: dict
    planned_loss_net: float
    reward_t1_net: float | None
    reward_t2_net: float | None
    rr_t1: float | None
    rr_t2: float | None
    rr_t1_net: float | None
    est_tax_t1: float | None
    open_risk_before: float
    open_risk_after: float
    exposure_after: float
    checks: list[Check] = field(default_factory=list)
    verdict: str = "Avoid"
    verdict_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [asdict(c) for c in self.checks]
        return d


def verdict_from_checks(checks: list[Check]) -> tuple[str, list[str]]:
    failed = [c for c in checks if not c.passed]
    if any(c.severity == "hard" for c in failed):
        return "Avoid", [c.detail for c in failed if c.severity == "hard"]
    if any(c.severity == "soft" for c in failed):
        return "Wait", [c.detail for c in failed if c.severity == "soft"]
    if failed:
        return "Watch", [c.detail for c in failed]
    return "Plan eligible", ["All risk and setup checks passed. This is a plan, not a prediction."]


def evaluate_trade(ticker: str, entry: float, stop: float, target1: float | None, target2: float | None,
                   equity: float, cash_available: float, open_positions: list[OpenPositionRisk],
                   cfg: TradingSettings, extra_checks: list[Check] | None = None) -> TradeEvaluation:
    checks: list[Check] = []
    valid = entry > 0 and stop > 0 and stop < entry
    checks.append(Check("Long-only stop below entry", valid,
                        "Stop must be below entry for a long trade." if not valid else f"Stop {stop:.2f} < entry {entry:.2f}"))
    if target1 is not None:
        ok = target1 > entry
        checks.append(Check("Target above entry", ok, "Target 1 must be above entry." if not ok else
                            f"T1 {target1:.2f} > entry"))
    size = position_size(equity, cfg.risk_per_trade_pct, entry, stop, cfg.share_increment, cash_available) \
        if valid else position_size(0, 0, 0, 0)
    checks.append(Check("Position fits risk budget", not size.unsuitable, size.message))

    sh = size.shares
    costs_stop = round_trip_costs(entry, stop, sh, cfg)
    costs_t1 = round_trip_costs(entry, target1, sh, cfg) if target1 else {"total": 0.0}
    planned_loss_net = round(size.planned_loss_gross + costs_stop["total"], 2)
    reward_t1 = round((target1 - entry) * sh - costs_t1["total"], 2) if target1 else None
    reward_t2 = round((target2 - entry) * sh - round_trip_costs(entry, target2, sh, cfg)["total"], 2) if target2 else None
    rr1 = reward_risk(entry, stop, target1) if valid else None
    rr2 = reward_risk(entry, stop, target2) if valid else None
    rr1_net = (reward_t1 / planned_loss_net) if (reward_t1 is not None and planned_loss_net > 0) else None
    tax = round(max(0.0, reward_t1) * cfg.est_tax_rate_pct / 100, 2) if reward_t1 is not None else None

    if rr1 is not None:
        if rr1 < 1:
            checks.append(Check("Reward:risk ≥ 1", False, f"R:R to T1 is {rr1:.2f} (< 1) — reward does not justify risk."))
        else:
            checks.append(Check(f"Reward:risk ≥ {cfg.min_reward_risk:g}", rr1 >= cfg.min_reward_risk,
                                f"R:R to T1 is {rr1:.2f} (gross), {rr1_net:.2f} after est. costs" if rr1_net
                                else f"R:R to T1 is {rr1:.2f}", "soft"))
    if sh > 0 and planned_loss_net > 0:
        cost_share = costs_stop["total"] / planned_loss_net
        checks.append(Check("Costs < 25% of planned loss", cost_share < 0.25,
                            f"Estimated costs are {cost_share * 100:.0f}% of the planned loss "
                            f"(${costs_stop['total']:.2f} of ${planned_loss_net:.2f}).", "soft"))

    open_risk = sum(p.risk for p in open_positions)
    new_risk = planned_loss_net if sh > 0 else 0.0
    max_open = equity * cfg.max_open_risk_pct / 100
    checks.append(Check("Aggregate open risk within limit", open_risk + new_risk <= max_open + 0.005,
                        f"Open risk ${open_risk:.2f} + this trade ${new_risk:.2f} = ${open_risk + new_risk:.2f} "
                        f"vs limit ${max_open:.2f} ({cfg.max_open_risk_pct:g}% of equity).", "soft"))
    n_open = len([p for p in open_positions if p.qty > 0])
    checks.append(Check("Max simultaneous positions", n_open < cfg.max_positions,
                        f"{n_open} open of max {cfg.max_positions}.", "soft"))
    if any(p.ticker.upper() == ticker.upper() for p in open_positions):
        checks.append(Check("No adding to an existing position", False,
                            f"{ticker} is already open. Adding/averaging is not part of the plan.", "soft"))
    exposure = sum(p.value for p in open_positions) + size.position_value
    checks.append(Check("No leverage (exposure ≤ equity)", exposure <= equity + 0.01,
                        f"Total exposure after trade ${exposure:.2f} vs equity ${equity:.2f}."))
    checks.extend(extra_checks or [])
    verdict, reasons = verdict_from_checks(checks)
    return TradeEvaluation(ticker.upper(), entry, stop, target1, target2, size, costs_stop, costs_t1,
                           planned_loss_net, reward_t1, reward_t2, rr1, rr2, rr1_net, tax,
                           round(open_risk, 2), round(open_risk + new_risk, 2), round(exposure, 2),
                           checks, verdict, reasons)


def context_checks(snap: dict, days_to_earnings: int | None, regime_label: str | None,
                   holding_days: int = 28) -> list[Check]:
    """Setup/market checks derived from the technical snapshot and calendar."""
    out = []
    if "error" in snap:
        return [Check("Price data available", False, snap["error"])]
    out.append(Check("Above 50DMA & 200DMA", bool(snap["above_sma50"] and snap["above_sma200"]),
                     f"Trend: {snap['trend']}", "info"))
    out.append(Check("Not overextended", not snap["overextended"],
                     "Extended >2.5 ATR above 20DMA or RSI > 75 — wait for a pullback/base."
                     if snap["overextended"] else "Not extended.", "soft"))
    if days_to_earnings is not None and 0 <= days_to_earnings <= holding_days:
        out.append(Check("No earnings inside holding period", False,
                         f"Earnings in {days_to_earnings} days — overnight gap risk can blow through the stop.",
                         "soft"))
    elif days_to_earnings is None:
        out.append(Check("Earnings date known", False, "Next earnings date unavailable — verify on company IR site.",
                         "info"))
    if regime_label and any(k in regime_label for k in ("Risk-off", "stress")):
        out.append(Check("Market regime supportive", False, f"Regime: {regime_label}.", "soft"))
    return out
