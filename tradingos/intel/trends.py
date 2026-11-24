"""Global Trends Radar: evidence-based theme classification.

For each theme in config/themes.json:
  * basket   = equal-weight daily-rebalanced index of the theme's proxies (or its companies if no proxy has data)
  * momentum = basket return and relative strength (RS, percentage points) vs its benchmark over 1M/3M/6M
  * trend    = basket vs its 50/200-day averages; extension = % above 200DMA and RSI(14)
  * breadth  = share of the theme's companies above their 50-day average
  * attention= theme news stories in the last 7 days vs the weekly average of the previous 28 days
Classification is a fixed rule ladder (METHODOLOGY) — every label lists the metric values that triggered it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tradingos.analysis import indicators as ind
from tradingos.config import PROJECT_ROOT
from tradingos.data.news import kw_hit
from tradingos.data.providers import get_market_provider

STAGES = ["Emerging", "Gaining momentum", "Established", "Crowded", "Weakening", "Out of favour", "No clear trend"]
METHODOLOGY = [
    ("Crowded", "RS 3M ≥ +8 pp AND (basket ≥ 20% above its 200DMA OR RSI(14) ≥ 75) — strong but stretched; "
                "late entrants face poor risk/reward."),
    ("Weakening", "RS 3M > 0 but RS 1M ≤ −3 pp (leadership fading), OR RS 6M > 0 with RS 3M < 0 and basket "
                  "below its 50DMA."),
    ("Gaining momentum", "RS 1M > 0 AND RS 3M > 0 AND (accelerating: RS 1M > RS 3M ÷ 3, OR news attention ratio ≥ 1.5)."),
    ("Established", "RS 3M > 0 AND RS 6M > 0 AND basket above its 200DMA."),
    ("Emerging", "RS 1M > 0 while RS 3M ≤ 0 (turning up from underperformance), OR news attention ratio ≥ 1.5 "
                 "with RS 1M > 0."),
    ("Out of favour", "RS 3M < 0 AND RS 6M < 0."),
    ("No clear trend", "None of the above."),
]


def load_themes() -> list[dict]:
    with open(PROJECT_ROOT / "config" / "themes.json") as f:
        return json.load(f)["themes"]


def all_symbols(themes: list[dict]) -> list[str]:
    syms = set()
    for t in themes:
        syms |= set(t["proxies"]) | set(t["companies"]) | {t["benchmark"]}
    return sorted(syms)


def basket_index(frames: dict[str, pd.DataFrame], members: list[str]) -> pd.Series | None:
    rets = [frames[m]["Close"].pct_change() for m in members if m in frames and len(frames[m]) > 30]
    if not rets:
        return None
    r = pd.concat(rets, axis=1).mean(axis=1, skipna=True).dropna()
    return (1 + r).cumprod() * 100 if len(r) else None


def _ret(s: pd.Series, n: int) -> float | None:
    return ind.pct_return(s, n) if s is not None and len(s) > n else None


def theme_metrics(theme: dict, frames: dict[str, pd.DataFrame]) -> dict:
    members = [p for p in theme["proxies"] if p in frames] or [c for c in theme["companies"] if c in frames]
    basis = "proxies" if any(p in frames for p in theme["proxies"]) else "companies"
    idx = basket_index(frames, members)
    bench = frames.get(theme["benchmark"], pd.DataFrame()).get("Close")
    m: dict = {"basket_members": members, "basket_basis": basis, "benchmark": theme["benchmark"]}
    if idx is None or bench is None or len(idx) < 130:
        m["error"] = "Insufficient price history for the theme basket or benchmark."
        return m
    bench = bench.dropna()
    for label, n in (("1M", 21), ("3M", 63), ("6M", 126)):
        br, bb = _ret(idx, n), _ret(bench, n)
        m[f"ret_{label}"] = None if br is None else round(br, 2)
        m[f"rs_{label}"] = None if br is None or bb is None else round(br - bb, 2)
    s50, s200 = idx.rolling(50).mean().iloc[-1], idx.rolling(200).mean().iloc[-1] if len(idx) >= 200 else np.nan
    m["above_50dma"] = bool(idx.iloc[-1] > s50)
    m["above_200dma"] = None if pd.isna(s200) else bool(idx.iloc[-1] > s200)
    m["pct_from_200dma"] = None if pd.isna(s200) else round(float(idx.iloc[-1] / s200 - 1) * 100, 1)
    rsi = ind.rsi(idx, 14).iloc[-1]
    m["rsi14"] = None if pd.isna(rsi) else round(float(rsi), 1)
    comp = [c for c in theme["companies"] if c in frames and len(frames[c]) >= 50]
    if comp:
        above = sum(frames[c]["Close"].iloc[-1] > frames[c]["Close"].tail(50).mean() for c in comp)
        m["breadth_above_50dma_pct"] = round(above / len(comp) * 100)
    m["as_of"] = idx.index[-1].date().isoformat()
    m["series"] = idx
    m["bench_series"] = bench
    return m


def news_attention(theme: dict, news: pd.DataFrame, now: datetime, recent: int = 7, base: int = 28) -> dict:
    if news is None or news.empty:
        return {"stories_7d": 0, "attention_ratio": None, "pos_share": None, "neg_share": None, "matches": news}
    kws = theme["keywords"]
    mask = [any(kw_hit(f" {h} {s or ''} ", k) for k in kws) for h, s in zip(news["headline"], news["summary"])]
    hit = news[mask]
    pub = pd.to_datetime(hit["published_utc"])
    r = hit[pub >= now - timedelta(days=recent)]
    b = hit[(pub < now - timedelta(days=recent)) & (pub >= now - timedelta(days=recent + base))]
    base_rate = len(b) / (base / recent)
    from tradingos.intel.geopolitics import MIN_BASE_STORIES, baseline_ready, collecting_since
    ready = baseline_ready(collecting_since(news), now, recent, base) and len(b) >= MIN_BASE_STORIES
    return {"stories_7d": len(r), "prior_weekly_avg": round(base_rate, 1) if ready else None,
            "attention_ratio": round(len(r) / base_rate, 2) if ready and base_rate > 0 else None,
            "baseline_ready": ready,
            "pos_share": round((r["sentiment"] == "positive").mean() * 100) if len(r) else None,
            "neg_share": round((r["sentiment"] == "negative").mean() * 100) if len(r) else None,
            "matches": hit}


def classify(m: dict, attn: float | None) -> tuple[str, str]:
    if m.get("error"):
        return "No clear trend", m["error"]
    rs1, rs3, rs6 = m.get("rs_1M"), m.get("rs_3M"), m.get("rs_6M")
    if rs1 is None or rs3 is None or rs6 is None:
        return "No clear trend", "Missing relative-strength inputs."
    ext, rsi = m.get("pct_from_200dma"), m.get("rsi14")
    vals = f"RS 1M {rs1:+.1f}pp · 3M {rs3:+.1f}pp · 6M {rs6:+.1f}pp"
    a = attn if attn is not None else 0
    if rs3 >= 8 and ((ext is not None and ext >= 20) or (rsi is not None and rsi >= 75)):
        return "Crowded", f"{vals}; {ext:+.1f}% vs 200DMA, RSI {rsi}" if ext is not None else vals
    if (rs3 > 0 and rs1 <= -3) or (rs6 > 0 and rs3 < 0 and not m.get("above_50dma")):
        return "Weakening", f"{vals}; above 50DMA: {m.get('above_50dma')}"
    if rs1 > 0 and rs3 > 0 and (rs1 > rs3 / 3 or a >= 1.5):
        return "Gaining momentum", f"{vals}; attention ratio {attn}"
    if rs3 > 0 and rs6 > 0 and m.get("above_200dma"):
        return "Established", f"{vals}; above 200DMA"
    if (rs1 > 0 and rs3 <= 0) or (a >= 1.5 and rs1 > 0):
        return "Emerging", f"{vals}; attention ratio {attn}"
    if rs3 < 0 and rs6 < 0:
        return "Out of favour", vals
    return "No clear trend", vals


def radar(news: pd.DataFrame, now: datetime, force: bool = False) -> tuple[pd.DataFrame, dict, dict]:
    """Returns (table, per-theme detail dict, meta)."""
    themes = load_themes()
    res = get_market_provider().history(all_symbols(themes), period="2y", force=force)
    frames = res.data or {}
    rows, detail = [], {}
    for t in themes:
        m = theme_metrics(t, frames)
        att = news_attention(t, news, now)
        stage, why = classify(m, att["attention_ratio"])
        detail[t["name"]] = {"theme": t, "metrics": m, "attention": att, "stage": stage, "why": why}
        rows.append({"Theme": t["name"], "Group": t["group"], "Stage": stage, "RS 1M (pp)": m.get("rs_1M"),
                     "RS 3M (pp)": m.get("rs_3M"), "RS 6M (pp)": m.get("rs_6M"), "Return 3M %": m.get("ret_3M"),
                     "vs 200DMA %": m.get("pct_from_200dma"), "RSI14": m.get("rsi14"),
                     "Breadth >50DMA %": m.get("breadth_above_50dma_pct"), "News 7d": att["stories_7d"],
                     "Attention ratio": att["attention_ratio"], "Benchmark": t["benchmark"],
                     "Basket": f"{m['basket_basis']}: {', '.join(m['basket_members'])}", "Evidence": why,
                     "As of": m.get("as_of")})
    meta = {"source": res.source, "retrieved_at_utc": res.retrieved_at.strftime("%Y-%m-%d %H:%M UTC"),
            "missing": res.missing, "error": res.error}
    return pd.DataFrame(rows), detail, meta


def briefing_rows(table: pd.DataFrame) -> list[dict]:
    if table is None or table.empty:
        return []
    keep = ["Theme", "Group", "Stage", "RS 1M (pp)", "RS 3M (pp)", "RS 6M (pp)", "vs 200DMA %", "News 7d",
            "Attention ratio", "Evidence"]
    return table[keep].where(pd.notna(table[keep]), None).to_dict("records")
