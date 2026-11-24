"""Cross-market snapshot: last price, 1D/1W/1M/3M/YTD/1Y performance, per-exchange freshness.

One batched provider call covers every registered instrument (cached by the provider for 15 min),
so all intelligence pages and briefings share the same numbers and timestamps.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from tradingos.analysis import indicators as ind
from tradingos.data.base import Freshness
from tradingos.data.providers import get_market_provider
from tradingos.intel.freshness import bar_freshness
from tradingos.intel.instruments import INSTRUMENTS, MARKETS, Instrument

PERF_COLS = ["1D %", "1W %", "1M %", "3M %", "YTD %", "1Y %"]


def all_symbols() -> list[str]:
    return list(dict.fromkeys(i.symbol for i in INSTRUMENTS))


def load_histories(force: bool = False, period: str = "2y"):
    """DataResult[dict[symbol, OHLCV DataFrame]] for every registered instrument."""
    return get_market_provider().history(all_symbols(), period=period, force=force)


def perf_row(inst: Instrument, df: pd.DataFrame | None, now: datetime | None = None) -> dict:
    base = {"Name": inst.name, "Symbol": inst.symbol, "Group": inst.group, "Market": MARKETS[inst.market].label,
            "Unit": inst.unit, "Note": inst.note}
    if df is None or len(df) < 2:
        fresh, note = bar_freshness(None, inst.market, now)
        return {**base, "Last": None, **{c: None for c in PERF_COLS}, "1D chg": None, "Above 200DMA": None,
                "Last bar": None, "Freshness": fresh.value, "Freshness note": note, "sparkline": []}
    c = df["Close"].dropna()
    last_bar = c.index[-1].date()
    fresh, note = bar_freshness(last_bar, inst.market, now)
    ytd_base = c[c.index.year < c.index[-1].year]
    s200 = ind.sma(c, 200).iloc[-1] if len(c) >= 200 else None
    return {
        **base,
        "Last": round(float(c.iloc[-1]), 4),
        "1D chg": round(float(c.iloc[-1] - c.iloc[-2]), 4),
        "1D %": ind.pct_return(c, 1), "1W %": ind.pct_return(c, 5), "1M %": ind.pct_return(c, 21),
        "3M %": ind.pct_return(c, 63),
        "YTD %": (float(c.iloc[-1] / ytd_base.iloc[-1] - 1) * 100) if len(ytd_base) else None,
        "1Y %": ind.pct_return(c, 252),
        "Above 200DMA": bool(c.iloc[-1] > s200) if s200 is not None and pd.notna(s200) else None,
        "Last bar": last_bar.isoformat(),
        "Freshness": fresh.value, "Freshness note": note,
        "sparkline": c.tail(30).round(4).tolist(),
    }


def snapshot(force: bool = False, now: datetime | None = None) -> tuple[pd.DataFrame, dict]:
    """All instruments → one table. meta carries source, retrieval time, errors and missing symbols."""
    res = load_histories(force=force)
    frames = res.data or {}
    rows = [perf_row(i, frames.get(i.symbol), now) for i in INSTRUMENTS]
    df = pd.DataFrame(rows)
    missing = sorted(df.loc[df["Last"].isna(), "Symbol"].unique().tolist())
    meta = {"source": res.source, "retrieved_at_utc": res.retrieved_at.strftime("%Y-%m-%d %H:%M UTC"),
            "error": res.error, "missing": missing,
            "note": "Daily bars from a free, delayed source. Never real-time; each row shows its own last-bar "
                    "date and exchange-aware freshness."}
    return df, meta


def group(df: pd.DataFrame, name: str) -> pd.DataFrame:
    return df[df["Group"] == name].reset_index(drop=True) if len(df) else df


def row(df: pd.DataFrame, symbol: str) -> dict | None:
    r = df[df["Symbol"] == symbol]
    if r.empty or pd.isna(r["Last"].iloc[0]):
        return None
    return r.iloc[0].to_dict()


def rel_perf(df: pd.DataFrame, a: str, b: str, col: str = "1M %") -> float | None:
    ra, rb = row(df, a), row(df, b)
    if not ra or not rb or ra.get(col) is None or rb.get(col) is None or pd.isna(ra[col]) or pd.isna(rb[col]):
        return None
    return round(float(ra[col]) - float(rb[col]), 2)


def close_series(symbol: str, period: str = "2y", force: bool = False) -> pd.Series | None:
    res = load_histories(force=force, period=period)
    if not res.ok or symbol not in res.data:
        return None
    return res.data[symbol]["Close"].dropna()


# ----------------------------------------------------------------------------- risk appetite
def _sig(name: str, value: str, reading: str, rule: str) -> dict:
    return {"Signal": name, "Value": value, "Reading": reading, "Rule": rule}


def risk_appetite(df: pd.DataFrame, hy_spread: float | None = None) -> dict:
    """Transparent cross-asset risk-on / risk-off checklist. Each signal states its rule; not a forecast."""
    sigs: list[dict] = []
    vix = row(df, "^VIX")
    if vix:
        v = vix["Last"]
        reading = "Risk-on" if v < 18 else "Risk-off" if v > 25 else "Neutral"
        sigs.append(_sig("VIX level", f"{v:.1f}", reading, "<18 risk-on · 18–25 neutral · >25 risk-off"))
    spx = row(df, "^GSPC")
    if spx and spx.get("Above 200DMA") is not None:
        sigs.append(_sig("S&P 500 vs 200-day average", "above" if spx["Above 200DMA"] else "below",
                         "Risk-on" if spx["Above 200DMA"] else "Risk-off", "Above 200DMA = long-term uptrend intact"))
    pairs = [
        ("High yield vs IG credit (HYG−LQD, 1M)", "HYG", "LQD", 0.5, "Junk outperforming = credit appetite"),
        ("Copper vs gold (1M)", "HG=F", "GC=F", 2.0, "Copper beating gold = growth optimism; gold beating copper = caution"),
        ("Small caps vs S&P 500 (RUT−SPX, 1M)", "^RUT", "^GSPC", 1.0, "Small caps leading = broad risk appetite"),
        ("Equal-weight vs cap-weight (RSP−SPX, 1M)", "RSP", "^GSPC", 1.0, "Equal-weight leading = broader participation"),
        ("Semiconductors vs S&P 500 (SMH−SPX, 1M)", "SMH", "^GSPC", 2.0, "Semis leading = cyclical/tech risk appetite"),
    ]
    for name, a, b, thr, rule in pairs:
        d = rel_perf(df, a, b)
        if d is not None:
            reading = "Risk-on" if d > thr else "Risk-off" if d < -thr else "Neutral"
            sigs.append(_sig(name, f"{d:+.2f} pp", reading, f"{rule} (±{thr}pp band = neutral)"))
    jpy = row(df, "JPY=X")
    if jpy and jpy.get("1W %") is not None and pd.notna(jpy["1W %"]):
        w = jpy["1W %"]
        reading = "Risk-off" if w < -2 else "Neutral"
        sigs.append(_sig("USD/JPY 1-week change", f"{w:+.2f}%", reading,
                         "A sharp yen rally (USD/JPY < −2% in a week) has coincided with carry-trade unwinds"))
    dxy = row(df, "DX-Y.NYB")
    if dxy and dxy.get("1M %") is not None and pd.notna(dxy["1M %"]):
        m = dxy["1M %"]
        reading = "Risk-off" if m > 2 else "Risk-on" if m < -2 else "Neutral"
        sigs.append(_sig("US dollar index 1-month change", f"{m:+.2f}%", reading,
                         "A fast-rising dollar tightens global financial conditions (±2% band = neutral)"))
    if hy_spread is not None:
        reading = "Risk-on" if hy_spread < 3.5 else "Risk-off" if hy_spread > 5 else "Neutral"
        sigs.append(_sig("US high-yield credit spread (FRED)", f"{hy_spread:.2f}%", reading,
                         "<3.5% calm · 3.5–5% neutral · >5% credit stress"))
    on = sum(s["Reading"] == "Risk-on" for s in sigs)
    off = sum(s["Reading"] == "Risk-off" for s in sigs)
    n = len(sigs)
    if n == 0:
        label = "Unknown (no data)"
    elif on - off >= max(2, n // 3):
        label = "Risk-on"
    elif off - on >= max(2, n // 3):
        label = "Risk-off"
    else:
        label = "Mixed"
    return {"label": label, "risk_on": on, "risk_off": off, "signals": sigs,
            "methodology": "Each signal is a fixed, published rule over delayed daily data. Label = Risk-on/off when "
                           "one side leads by at least max(2, n/3) signals; otherwise Mixed. A checklist, not a forecast."}


def freshness_summary(df: pd.DataFrame) -> dict[str, int]:
    return df["Freshness"].value_counts().to_dict() if len(df) else {}


def is_live_like(freshness: str) -> bool:
    return freshness in (Freshness.INTRADAY_DELAYED.value, Freshness.CURRENT.value)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
