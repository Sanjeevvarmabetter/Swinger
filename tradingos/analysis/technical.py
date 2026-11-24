"""Technical analysis built ONLY from supplied price data.

Produces a structured snapshot (trend, levels, momentum, volume, setup, extension) that the
company research snapshots share. Support/resistance come from clustered
swing pivots — never invented.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradingos.analysis import indicators as ind


@dataclass
class Level:
    price: float
    touches: int
    last_touch: str
    kind: str  # support | resistance

    def as_dict(self) -> dict:
        return {"price": round(self.price, 2), "touches": self.touches, "last_touch": self.last_touch,
                "kind": self.kind}


def find_pivots(df: pd.DataFrame, k: int = 5) -> tuple[pd.Series, pd.Series]:
    """Swing highs/lows: bar whose high (low) is the max (min) of the surrounding 2k+1 bars."""
    hi, lo = df["High"], df["Low"]
    win = 2 * k + 1
    is_hi = hi == hi.rolling(win, center=True, min_periods=win).max()
    is_lo = lo == lo.rolling(win, center=True, min_periods=win).min()
    return hi[is_hi], lo[is_lo]


def cluster_levels(points: pd.Series, tolerance: float) -> list[tuple[float, int, pd.Timestamp]]:
    """Group pivot prices within `tolerance` → (mean price, touches, last date)."""
    if points.empty:
        return []
    items = sorted(zip(points.values, points.index), key=lambda x: x[0])
    clusters: list[list] = [[items[0]]]
    for p, d in items[1:]:
        if abs(p - np.mean([x[0] for x in clusters[-1]])) <= tolerance:
            clusters[-1].append((p, d))
        else:
            clusters.append([(p, d)])
    return [(float(np.mean([x[0] for x in c])), len(c), max(x[1] for x in c)) for c in clusters]


def support_resistance(df: pd.DataFrame, k: int = 5, lookback: int = 250, max_levels: int = 3
                       ) -> tuple[list[Level], list[Level]]:
    d = df.tail(lookback)
    if len(d) < 2 * k + 2:
        return [], []
    price = float(d["Close"].iloc[-1])
    a = ind.atr(d).iloc[-1]
    tol = max(float(a) * 0.5 if pd.notna(a) else 0, price * 0.015)
    highs, lows = find_pivots(d, k)
    clusters = cluster_levels(pd.concat([highs, lows]), tol)
    sup, res = [], []
    for p, n, last in clusters:
        lvl_kind = "support" if p < price else "resistance"
        lvl = Level(p, n, pd.Timestamp(last).date().isoformat(), lvl_kind)
        (sup if p < price else res).append(lvl)
    # Period extremes are real levels too (52w high may have no confirmed pivot yet)
    hh = float(d["High"].max())
    if hh > price and not any(abs(r.price - hh) <= tol for r in res):
        res.append(Level(hh, 1, d["High"].idxmax().date().isoformat(), "resistance (period high)"))
    sup.sort(key=lambda x: -x.price)
    res.sort(key=lambda x: x.price)
    return sup[:max_levels], res[:max_levels]


def market_structure(df: pd.DataFrame, k: int = 5) -> str:
    highs, lows = find_pivots(df.tail(180), k)
    if len(highs) < 2 or len(lows) < 2:
        return "Insufficient swing points"
    hh = highs.iloc[-1] > highs.iloc[-2]
    hl = lows.iloc[-1] > lows.iloc[-2]
    if hh and hl:
        return "Higher highs & higher lows"
    if not hh and not hl:
        return "Lower highs & lower lows"
    return "Mixed (higher highs, lower lows)" if hh else "Mixed (lower highs, higher lows)"


def classify_trend(close: float, s20, s50, s200, slope50) -> str:
    if s50 is None or s20 is None:
        return "Undetermined (insufficient history)"
    if s200 is None:
        return "Uptrend (short history)" if close > s20 > s50 else "Undetermined (short history)"
    if close > s50 > s200 and (slope50 or 0) > 0:
        return "Strong uptrend" if s20 and close > s20 else "Uptrend (short-term pullback)"
    if close < s50 < s200 and (slope50 or 0) < 0:
        return "Downtrend"
    if close > s200:
        return "Sideways / recovering above 200DMA"
    return "Sideways / weak below 200DMA"


def analyze(df: pd.DataFrame, bench: pd.DataFrame | None = None, breakout_lookback: int = 55,
            rs_lookback: int = 63, pivot_k: int = 5, rel_vol_confirm: float = 1.5) -> dict:
    """Full deterministic snapshot of one instrument. All numbers come from df."""
    if df is None or len(df) < 30:
        return {"error": "Insufficient price history (need ≥ 30 bars)", "bars": 0 if df is None else len(df)}
    d = ind.add_all(df)
    last = d.iloc[-1]
    c = float(last["Close"])
    f = ind.finite
    s20, s50, s100, s200 = (f(last[f"SMA{n}"]) for n in (20, 50, 100, 200))
    a = f(last["ATR14"])
    slope50 = ind.slope(d["SMA50"], 10)
    sup, res = support_resistance(d, k=pivot_k)
    prior_high = f(d["High"].iloc[-breakout_lookback - 1:-1].max()) if len(d) > breakout_lookback else None
    rel_vol = f(last["RelVol20"])
    rs = ind.relative_strength(d["Close"], bench["Close"], rs_lookback) if bench is not None else None
    rsi_v = f(last["RSI14"])
    macd_v, macd_sig = f(last["MACD"]), f(last["MACD_signal"])
    hi_52 = float(d["High"].tail(252).max())
    lo_52 = float(d["Low"].tail(252).min())
    ext_atr = (c - s20) / a if (s20 and a) else None

    snap = {
        "bars": len(d), "as_of": d.index[-1].date().isoformat(), "close": round(c, 2),
        "change_1d_pct": ind.pct_return(d["Close"], 1), "return_1m_pct": ind.pct_return(d["Close"], 21),
        "return_3m_pct": ind.pct_return(d["Close"], 63), "return_6m_pct": ind.pct_return(d["Close"], 126),
        "sma20": s20, "sma50": s50, "sma100": s100, "sma200": s200,
        "above_sma20": s20 is not None and c > s20, "above_sma50": s50 is not None and c > s50,
        "above_sma200": s200 is not None and c > s200, "sma50_slope_10d_pct": slope50,
        "rsi14": rsi_v, "macd": macd_v, "macd_signal": macd_sig,
        "macd_bullish": macd_v is not None and macd_sig is not None and macd_v > macd_sig,
        "atr14": a, "atr_pct": (a / c * 100) if a else None,
        "rel_volume": rel_vol, "avg_dollar_volume_20d": f(last["AvgDollarVol20"]),
        "rs_vs_spy_pp": rs, "high_52w": round(hi_52, 2), "low_52w": round(lo_52, 2),
        "pct_from_52w_high": (c / hi_52 - 1) * 100,
        "breakout_level": prior_high, "extension_atr_above_sma20": ext_atr,
        "trend": classify_trend(c, s20, s50, s200, slope50),
        "structure": market_structure(d, pivot_k),
        "supports": [l.as_dict() for l in sup], "resistances": [l.as_dict() for l in res],
    }
    # volume confirmation over last 5 sessions: up-day volume vs down-day volume
    tail = d.tail(10)
    up = tail[tail["Close"] > tail["Close"].shift(1)]["Volume"].mean()
    dn = tail[tail["Close"] < tail["Close"].shift(1)]["Volume"].mean()
    snap["up_down_volume_ratio_10d"] = f(up / dn) if pd.notna(up) and pd.notna(dn) and dn else None
    snap["setups"] = detect_setups(snap, rel_vol_confirm)
    snap["overextended"] = bool((ext_atr is not None and ext_atr > 2.5) or (rsi_v is not None and rsi_v > 75))
    return snap


def detect_setups(s: dict, rel_vol_confirm: float = 1.5) -> list[str]:
    out = []
    c, bl, rsi_v, rv = s["close"], s["breakout_level"], s["rsi14"], s["rel_volume"]
    uptrend = s["above_sma50"] and s["above_sma200"]
    if bl and c > bl:
        out.append("Breakout (volume-confirmed)" if rv and rv >= rel_vol_confirm else "Breakout (unconfirmed volume)")
    elif bl and uptrend and c >= bl * 0.97:
        out.append("Near breakout (within 3% of range high)")
    if uptrend and s["sma20"] and s["atr14"] and rsi_v is not None:
        near20 = abs(c - s["sma20"]) <= s["atr14"]
        near50 = s["sma50"] and abs(c - s["sma50"]) <= s["atr14"]
        if (near20 or near50) and 38 <= rsi_v <= 58 and s["pct_from_52w_high"] <= -3:
            out.append("Pullback to " + ("20DMA" if near20 else "50DMA") + " in uptrend")
    if (s["above_sma20"] and uptrend and s["macd_bullish"] and rsi_v is not None and 55 <= rsi_v <= 75
            and (s["rs_vs_spy_pp"] or 0) > 0):
        out.append("Momentum continuation")
    return out


def _stop_from(entry: float, support: float | None, a: float) -> tuple[float, str]:
    if support is not None:
        cand = support - 0.25 * a
        if entry - 3 * a <= cand <= entry - 0.75 * a:
            return cand, f"0.25×ATR below support {support:.2f}"
    return entry - 2 * a, "2×ATR below entry (no support within 0.75–3 ATR)"
