"""Minimal, honest single-ticker backtester for the app's own setup rules.

Rules evaluated on the daily close; entries at the NEXT bar's open; stop checked before
target on each bar (conservative); exits on stop, target, or max holding days.
Caveats (shown in UI): no survivorship correction, adjusted prices, simplified costs,
small samples, past ≠ future. Use it to sanity-check rules, not to "prove" an edge.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradingos.analysis import indicators as ind


@dataclass
class BTParams:
    rule: str = "pullback"         # pullback | breakout | momentum
    atr_stop_mult: float = 2.0
    target_r: float = 2.0
    max_hold_days: int = 20
    cost_bps_per_side: float = 10.0
    breakout_lookback: int = 55


def signals(df: pd.DataFrame, p: BTParams) -> pd.Series:
    d = ind.add_all(df)
    c = d["Close"]
    trend = (c > d["SMA50"]) & (d["SMA50"] > d["SMA200"])
    if p.rule == "breakout":
        prior_high = d["High"].shift(1).rolling(p.breakout_lookback).max()
        sig = trend & (c > prior_high) & (d["RelVol20"] >= 1.5)
    elif p.rule == "momentum":
        sig = trend & (c > d["SMA20"]) & (d["MACD"] > d["MACD_signal"]) & d["RSI14"].between(55, 70)
    else:  # pullback: uptrend, close within 1 ATR of 20DMA, RSI 40-55, bullish close above prior high
        sig = (trend & ((c - d["SMA20"]).abs() <= d["ATR14"]) & d["RSI14"].between(40, 55)
               & (c > d["High"].shift(1)))
    return sig.fillna(False), d


def run_backtest(df: pd.DataFrame, p: BTParams) -> tuple[pd.DataFrame, dict]:
    sig, d = signals(df, p)
    trades, i, n = [], 0, len(d)
    idx = d.index
    while i < n - 1:
        if not sig.iloc[i] or pd.isna(d["ATR14"].iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        entry = d["Open"].iloc[entry_i]
        stop = entry - p.atr_stop_mult * d["ATR14"].iloc[i]
        risk = entry - stop
        target = entry + p.target_r * risk
        exit_px, exit_i, reason = None, None, None
        for j in range(entry_i, min(entry_i + p.max_hold_days, n)):
            lo, hi, op = d["Low"].iloc[j], d["High"].iloc[j], d["Open"].iloc[j]
            if lo <= stop:
                exit_px, exit_i, reason = (min(op, stop) if j > entry_i else stop), j, "stop"
                break
            if hi >= target:
                exit_px, exit_i, reason = (max(op, target) if j > entry_i else target), j, "target"
                break
        if exit_px is None:
            exit_i = min(entry_i + p.max_hold_days, n) - 1
            exit_px, reason = d["Close"].iloc[exit_i], "time"
        cost = (entry + exit_px) * p.cost_bps_per_side / 10_000
        r = (exit_px - entry - cost) / risk
        trades.append({"signal_date": idx[i].date(), "entry_date": idx[entry_i].date(), "entry": round(entry, 2),
                       "stop": round(stop, 2), "target": round(target, 2), "exit_date": idx[exit_i].date(),
                       "exit": round(exit_px, 2), "reason": reason, "r": round(r, 2),
                       "bars": exit_i - entry_i + 1})
        i = exit_i + 1  # one position at a time
    t = pd.DataFrame(trades)
    if t.empty:
        return t, {"trades": 0}
    wins = t[t["r"] > 0]
    stats = {"trades": len(t), "win_rate_pct": round(len(wins) / len(t) * 100, 1),
             "avg_r": round(t["r"].mean(), 2), "total_r": round(t["r"].sum(), 2),
             "profit_factor": round(wins["r"].sum() / -t[t["r"] < 0]["r"].sum(), 2) if (t["r"] < 0).any() else None,
             "max_consecutive_losses": int((t["r"] < 0).astype(int).groupby((t["r"] >= 0).cumsum()).sum().max()),
             "avg_bars": round(t["bars"].mean(), 1)}
    return t, stats
