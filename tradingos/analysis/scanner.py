"""Stock discovery engine.

Scores are transparent rule points (0–100) — a ranking aid, NOT a probability of success.
If nothing passes the filters, the scanner returns an empty result.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

import pandas as pd

from tradingos.analysis import indicators as ind
from tradingos.analysis.technical import analyze
from tradingos.data.base import DataResult
from tradingos.data.providers import SECTOR_ETFS, get_market_provider, load_universe
from tradingos.db.models import ScanRun
from tradingos.db.session import session_scope
from tradingos.settings import TradingSettings

CATEGORIES = {
    "momentum": "Strong momentum",
    "breakout": "Breakout candidates",
    "pullback": "Pullback opportunities",
    "sector_leaders": "Emerging sector leaders",
    "earnings": "Earnings-related",
    "ai_semis": "AI & semiconductors",
    "high_rs": "High relative strength",
    "unusual_volume": "Unusual volume",
}
SCORE_DISCLAIMER = ("Score = sum of transparent rule points (trend, relative strength, momentum, volume, "
                    "structure, sector). It ranks setups; it is NOT a probability or a validated edge.")
NON_TRADABLE_SECTORS = {"Index"}


@dataclass
class ScanOutput:
    candidates: pd.DataFrame
    categories: dict[str, list[str]]
    data: DataResult
    universe_size: int
    evaluated: int
    excluded: dict[str, int] = field(default_factory=dict)
    breadth_frames: dict[str, pd.DataFrame] | None = None
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def score_candidate(s: dict, rs_pct: float, sector_rank: int | None, cfg: TradingSettings) -> tuple[int, dict]:
    pts: dict[str, int] = {}
    pts["trend"] = (5 * s["above_sma20"] + 8 * s["above_sma50"] + 7 * s["above_sma200"]
                    + 5 * bool(s["sma50"] and s["sma200"] and s["sma50"] > s["sma200"]))
    pts["relative_strength"] = int(round(rs_pct * 20))
    rsi_v = s["rsi14"]
    pts["momentum"] = (8 if rsi_v is not None and cfg.rsi_min <= rsi_v <= cfg.rsi_max else 0) + 7 * s["macd_bullish"]
    rv = s["rel_volume"] or 0
    pts["volume"] = (8 if rv >= cfg.rel_volume_breakout else 4 if rv >= 1.0 else 0) + \
        (7 if (s["up_down_volume_ratio_10d"] or 0) > 1.2 else 0)
    st = s["structure"]
    pts["structure"] = 10 if st.startswith("Higher highs") else 4 if st.startswith("Mixed") else 0
    pts["sector"] = 10 if sector_rank is not None and sector_rank <= 3 else 5 if sector_rank is not None and sector_rank <= 6 else 0
    pts["overextension_penalty"] = -10 if s["overextended"] else 0
    total = max(0, min(100, sum(pts.values())))
    return total, pts


def _recent_gap_up(df: pd.DataFrame, days: int = 15) -> str | None:
    d = df.tail(days + 21).copy()
    d["gap"] = d["Open"] / d["Close"].shift(1) - 1
    d["rv"] = ind.relative_volume(df["Volume"]).reindex(d.index)
    hits = d.tail(days)[(d.tail(days)["gap"] > 0.04) & (d.tail(days)["rv"] > 2)]
    if hits.empty:
        return None
    day = hits.index[-1]
    held = df["Close"].iloc[-1] > df.loc[day, "Open"] * 0.98
    return f"{day.date()} gap +{hits['gap'].iloc[-1] * 100:.1f}% on {hits['rv'].iloc[-1]:.1f}× volume" + \
        (" (held)" if held else " (faded)")


def run_scan(cfg: TradingSettings, force: bool = False, with_earnings: bool = True,
             earnings_top_n: int = 25, persist: bool = True) -> ScanOutput:
    uni = load_universe(cfg.extra_tickers)
    prov = get_market_provider()
    tickers = list(uni["ticker"]) + list(SECTOR_ETFS.values()) + ["SPY"]
    res = prov.history(tickers, period="1y", force=force)
    if not res.ok:
        return ScanOutput(pd.DataFrame(), {k: [] for k in CATEGORIES}, res, len(uni), 0)
    frames = res.data
    spy = frames.get("SPY")
    meta = uni.set_index("ticker")

    # sector ranks by 3M RS of sector ETFs
    sector_rs = {}
    for sec, etf in SECTOR_ETFS.items():
        if etf in frames and spy is not None:
            sector_rs[sec] = ind.relative_strength(frames[etf]["Close"], spy["Close"], cfg.rs_lookback_days)
    ranked = sorted([k for k, v in sector_rs.items() if v is not None], key=lambda k: -sector_rs[k])
    sector_rank = {s: i + 1 for i, s in enumerate(ranked)}

    excluded = {"missing_data": sum(t not in frames for t in uni["ticker"]), "short_history": 0, "price": 0, "liquidity": 0, "index_etf": 0}
    snaps = {}
    for t in uni["ticker"]:
        if meta.loc[t, "sector"] in NON_TRADABLE_SECTORS:
            excluded["index_etf"] += 1
            continue
        df = frames.get(t)
        if df is None:
            continue
        if len(df) < (200 if cfg.require_above_200dma else 60):
            excluded["short_history"] += 1
            continue
        s = analyze(df, spy, breakout_lookback=cfg.breakout_lookback, rs_lookback=cfg.rs_lookback_days,
                    rel_vol_confirm=cfg.rel_volume_breakout)
        if "error" in s:
            excluded["short_history"] += 1
            continue
        if s["close"] < cfg.min_price:
            excluded["price"] += 1
            continue
        if (s["avg_dollar_volume_20d"] or 0) < cfg.min_avg_dollar_volume_m * 1e6:
            excluded["liquidity"] += 1
            continue
        snaps[t] = s

    rs_series = pd.Series({t: s["rs_vs_spy_pp"] for t, s in snaps.items()}).dropna()
    rs_pct = rs_series.rank(pct=True) if len(rs_series) else pd.Series(dtype=float)

    rows = []
    for t, s in snaps.items():
        sec = meta.loc[t, "sector"]
        themes = meta.loc[t, "themes"]
        trend_ok = s["above_sma50"] and (s["above_sma200"] or not cfg.require_above_200dma)
        pct = float(rs_pct.get(t, 0.0))
        score, breakdown = score_candidate(s, pct, sector_rank.get(sec), cfg)
        cats = []
        if trend_ok and "Momentum continuation" in s["setups"]:
            cats.append("momentum")
        if trend_ok and any(x.startswith(("Breakout", "Near breakout")) for x in s["setups"]):
            cats.append("breakout")
        if any(x.startswith("Pullback") for x in s["setups"]):
            cats.append("pullback")
        sec_etf = SECTOR_ETFS.get(sec)
        if (trend_ok and sector_rank.get(sec, 99) <= 3 and s["rs_vs_spy_pp"] is not None
                and sector_rs.get(sec) is not None and s["rs_vs_spy_pp"] > sector_rs[sec] and pct >= 0.7):
            cats.append("sector_leaders")
        if trend_ok and any(th in themes.split(";") for th in ("ai", "semis")) and score >= 50:
            cats.append("ai_semis")
        if trend_ok and pct >= 0.8:
            cats.append("high_rs")
        if (s["rel_volume"] or 0) >= cfg.rel_volume_unusual:
            cats.append("unusual_volume")
        gap = _recent_gap_up(frames[t])
        if gap and trend_ok:
            cats.append("earnings")
        if not cats:
            continue
        reasons = [f"{CATEGORIES[c]}" for c in cats]
        risks = []
        if s["overextended"]:
            risks.append("Extended — chasing risk; wait for consolidation/pullback")
        if not s["above_sma200"]:
            risks.append("Below 200DMA (long-term trend not confirmed)")
        if (s["rel_volume"] or 0) < 1 and any(c in cats for c in ("breakout",)):
            risks.append("Breakout lacks volume confirmation")
        if s["atr_pct"] and s["atr_pct"] > 5:
            risks.append(f"High volatility (ATR {s['atr_pct']:.1f}% of price) → wide stop, small size")
        if (s["change_1d_pct"] or 0) < -2 and "unusual_volume" in cats:
            risks.append("Unusual volume on a DOWN day — possible distribution")
        rows.append({
            "Ticker": t, "Company": meta.loc[t, "name"], "Sector": sec, "Themes": themes,
            "Price": s["close"], "As of": s["as_of"], "Score": score,
            "1D %": None if s.get("change_1d_pct") is None else round(s["change_1d_pct"], 2),
            "1W %": None if s.get("return_1w_pct") is None else round(s["return_1w_pct"], 2),
            "1M %": None if s.get("return_1m_pct") is None else round(s["return_1m_pct"], 1),
            "Trend": s["trend"], "Structure": s["structure"],
            "Above 20DMA": s.get("above_sma20"),
            "Above 50DMA": s.get("above_sma50"),
            "Above 200DMA": s.get("above_sma200"),
            "RS vs SPY (pp)": None if s["rs_vs_spy_pp"] is None else round(s["rs_vs_spy_pp"], 1),
            "RS pctile": round(pct * 100), "RSI": None if s["rsi14"] is None else round(s["rsi14"], 1),
            "Rel vol": None if s["rel_volume"] is None else round(s["rel_volume"], 2),
            "ATR %": None if s["atr_pct"] is None else round(s["atr_pct"], 2),
            "Setup": "; ".join(s["setups"]) or "—", "Categories": ",".join(cats),
            "Reason": "; ".join(reasons) + (f"; {gap}" if gap else ""), "Risks": "; ".join(risks) or "—",
            "Next earnings": None, "Earnings flag": "", "Score breakdown": json.dumps(breakdown),
            "Sector rank": sector_rank.get(sec), "_sector_etf": sec_etf,
        })

    cands = pd.DataFrame(rows)
    if len(cands):
        cands = cands.sort_values("Score", ascending=False).reset_index(drop=True)
        if with_earnings:
            today = date.today()
            for i in cands.index[:earnings_top_n]:
                er = prov.earnings(cands.at[i, "Ticker"])
                nd = er.data.get("next_date") if er.ok else None
                if nd:
                    cands.at[i, "Next earnings"] = nd.isoformat()
                    days = (nd - today).days
                    if days <= cfg.earnings_warning_days:
                        cands.at[i, "Earnings flag"] = f"⚠ Earnings in {days}d — overnight gap risk"
                        cats_i = cands.at[i, "Categories"].split(",")
                        if "earnings" not in cats_i:
                            cands.at[i, "Categories"] = ",".join(cats_i + ["earnings"])
    categories = {k: (list(cands.loc[cands["Categories"].str.split(",").apply(lambda c, k=k: k in c), "Ticker"])
                      if len(cands) else []) for k in CATEGORIES}
    out = ScanOutput(cands, categories, res, len(uni), len(snaps), excluded, frames)
    if persist:
        with session_scope() as sess:
            sess.add(ScanRun(data_as_of=str(res.as_of), universe_size=len(uni),
                             params_json=json.dumps(asdict(cfg), default=str),
                             results_json=cands.drop(columns=["_sector_etf"], errors="ignore").to_json(orient="records")
                             if len(cands) else "[]"))
    return out


def latest_scan() -> tuple[pd.DataFrame, datetime | None, str]:
    from sqlalchemy import select
    with session_scope() as s:
        row = s.scalars(select(ScanRun).order_by(ScanRun.run_at.desc()).limit(1)).first()
        if not row:
            return pd.DataFrame(), None, ""
        return pd.DataFrame(json.loads(row.results_json)), row.run_at, row.data_as_of
