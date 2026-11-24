"""US market overview: indices, indicators, sectors, breadth and a rule-based regime."""
from __future__ import annotations

import pandas as pd

from tradingos.analysis import indicators as ind
from tradingos.data.base import DataResult
from tradingos.data.providers import (INDEX_SYMBOLS, INDICATOR_SYMBOLS, OVERVIEW_SYMBOLS, SECTOR_ETFS,
                                      get_market_provider, load_universe)


def _perf_row(name: str, sym: str, df: pd.DataFrame) -> dict:
    c = df["Close"]
    s50 = ind.sma(c, 50).iloc[-1] if len(c) >= 50 else None
    s200 = ind.sma(c, 200).iloc[-1] if len(c) >= 200 else None
    ytd_base = c[c.index.year < c.index[-1].year]
    abs_1d = float(c.iloc[-1] - c.iloc[-2]) if len(c) >= 2 else 0.0
    return {
        "Name": name, "Symbol": sym, "Last": round(float(c.iloc[-1]), 2),
        "1D $": round(abs_1d, 2), "1D %": ind.pct_return(c, 1),
        "1W %": ind.pct_return(c, 5), "1M %": ind.pct_return(c, 21),
        "3M %": ind.pct_return(c, 63),
        "YTD %": (float(c.iloc[-1] / ytd_base.iloc[-1] - 1) * 100) if len(ytd_base) else None,
        "Above 50DMA": bool(c.iloc[-1] > s50) if pd.notna(s50) else None,
        "Above 200DMA": bool(c.iloc[-1] > s200) if pd.notna(s200) else None,
        "As of": c.index[-1].date().isoformat(),
        "sparkline": c.tail(20).tolist() if len(c) >= 2 else [],
    }


def index_overview(force: bool = False) -> tuple[pd.DataFrame, DataResult]:
    syms = {**OVERVIEW_SYMBOLS, **INDEX_SYMBOLS, **INDICATOR_SYMBOLS}
    res = get_market_provider().history(list(syms.values()) + ["SPY"], period="2y", force=force)
    rows = []
    if res.ok:
        for name, sym in syms.items():
            if sym in res.data and name not in [r["Name"] for r in rows]:
                rows.append(_perf_row(name, sym, res.data[sym]))
    return pd.DataFrame(rows), res


def sector_performance(force: bool = False) -> tuple[pd.DataFrame, DataResult]:
    res = get_market_provider().history(list(SECTOR_ETFS.values()) + ["SPY"], period="1y", force=force)
    rows = []
    if res.ok and "SPY" in res.data:
        spy = res.data["SPY"]["Close"]
        for sector, etf in SECTOR_ETFS.items():
            df = res.data.get(etf)
            if df is None:
                continue
            row = _perf_row(sector, etf, df)
            row["RS vs SPY 3M (pp)"] = ind.relative_strength(df["Close"], spy, 63)
            rows.append(row)
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("RS vs SPY 3M (pp)", ascending=False).reset_index(drop=True)
    return out, res


def universe_breadth(frames: dict[str, pd.DataFrame]) -> dict:
    """Breadth computed across the scan universe (NOT the full NYSE/Nasdaq A/D line)."""
    uni = load_universe()
    stocks = set(uni.loc[uni["type"] == "Stock", "ticker"])
    n = adv = dec = a20 = a50 = a200 = nh = nl = valid200 = 0
    for t, df in frames.items():
        if t not in stocks or len(df) < 60:
            continue
        c = df["Close"]
        n += 1
        if c.iloc[-1] > c.iloc[-2]:
            adv += 1
        elif c.iloc[-1] < c.iloc[-2]:
            dec += 1
        if len(c) >= 20 and c.iloc[-1] > c.tail(20).mean():
            a20 += 1
        if c.iloc[-1] > c.tail(50).mean():
            a50 += 1
        if len(c) >= 200:
            valid200 += 1
            a200 += int(c.iloc[-1] > c.tail(200).mean())
        if df["High"].iloc[-1] >= df["High"].tail(252).max():
            nh += 1
        if df["Low"].iloc[-1] <= df["Low"].tail(252).min():
            nl += 1
    if n == 0:
        return {"stocks": 0}
    return {
        "stocks": n, "advancers": adv, "decliners": dec, "ad_ratio": round(adv / dec, 2) if dec else None,
        "pct_above_20dma": round(a20 / n * 100, 1),
        "pct_above_50dma": round(a50 / n * 100, 1),
        "pct_above_200dma": round(a200 / valid200 * 100, 1) if valid200 else None,
        "new_52w_highs": nh, "new_52w_lows": nl,
        "note": f"Computed across {n} stocks in the scan universe — a proxy, not exchange-wide breadth."
    }


def market_regime(idx: pd.DataFrame, spy: pd.DataFrame | None, breadth: dict | None = None) -> dict:
    """Transparent rule-based regime. Each rule and its result is returned."""
    rules, score = [], 0
    if spy is not None and len(spy) >= 200:
        c = spy["Close"]
        s50, s200 = ind.sma(c, 50).iloc[-1], ind.sma(c, 200).iloc[-1]
        above200 = c.iloc[-1] > s200
        rules.append(("SPY above 200DMA", bool(above200)))
        rules.append(("SPY 50DMA above 200DMA", bool(s50 > s200)))
        rules.append(("SPY above 50DMA", bool(c.iloc[-1] > s50)))
        score += int(above200) * 2 + int(s50 > s200) + int(c.iloc[-1] > s50)
        rv = ind.relative_volume(spy["Volume"]).iloc[-1]
        down_day = c.iloc[-1] < c.iloc[-2]
        if pd.notna(rv) and rv > 1.3 and down_day:
            rules.append(("No heavy-volume SPY down day (distribution)", False))
        else:
            rules.append(("No heavy-volume SPY down day (distribution)", True))
            score += 1
    vix_row = idx[idx["Symbol"] == "^VIX"] if len(idx) else pd.DataFrame()
    vix = float(vix_row["Last"].iloc[0]) if len(vix_row) else None
    if vix is not None:
        rules.append((f"VIX below 20 (now {vix:.1f})", vix < 20))
        score += 1 if vix < 20 else (-1 if vix > 30 else 0)
    if breadth and breadth.get("pct_above_50dma") is not None:
        ok = breadth["pct_above_50dma"] >= 50
        rules.append((f"≥50% of universe above 50DMA (now {breadth['pct_above_50dma']}%)", ok))
        score += int(ok)
    max_score = 7
    if not rules:
        label = "Unknown (data unavailable)"
        category = "Unknown"
    elif vix is not None and vix > 30:
        label = "High-volatility stress"
        category = "High volatility"
    elif score >= 6:
        label = "Risk-on uptrend"
        category = "Risk-on / Bullish trend"
    elif score >= 4:
        label = "Uptrend under pressure / mixed"
        category = "Bullish trend (selective)"
    elif score >= 2:
        label = "Choppy / defensive"
        category = "Sideways / consolidation"
    else:
        label = "Risk-off / downtrend"
        category = "Risk-off / Bearish trend"
    guidance = {
        "Risk-on uptrend": "Environment supports swing longs; still respect position limits.",
        "Uptrend under pressure / mixed": "Be selective: only A-grade setups, consider smaller risk.",
        "Choppy / defensive": "Breakouts tend to fail more in chop; favour cash or very selective pullbacks.",
        "Risk-off / downtrend": "Most long setups fight the tape. Cash is a position.",
        "High-volatility stress": "Gaps and wide ranges make stops unreliable. Reduce activity.",
    }.get(label, "")
    return {
        "label": label, "category": category, "score": score, "max_score": max_score,
        "rules": rules, "vix": vix, "guidance": guidance
    }
