"""Daily market intelligence report: deterministic facts + optional Gemini interpretation."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from tradingos.analysis.scanner import latest_scan


def _fmt(v, suffix=""):
    return "n/a" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:+.2f}{suffix}"


def news_lines(df: pd.DataFrame, n: int = 10) -> list[str]:
    out = []
    for _, r in df.head(n).iterrows():
        ts = pd.Timestamp(r["published_utc"]).strftime("%Y-%m-%d %H:%M UTC") if pd.notna(r["published_utc"]) else "time n/a"
        extra = f" — _{r['impact']}_" if r.get("impact") else ""
        out.append(f"- [{r['headline']}]({r['url']}) · {r['source']} · {ts} · {r.get('info_type', '')}{extra}")
    return out


def deterministic_report(mc: dict) -> str:
    """Every statement here comes from fetched data with its timestamp."""
    lines = [f"# Daily US Market Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
             f"_Generated {mc['generated_at_utc']} · market status: {mc['market_status_now']} · "
             f"index data as of {mc['index_data_meta'].get('data_as_of')} ({mc['index_data_meta'].get('freshness')})_", ""]
    reg = mc["regime"]
    lines += ["## 1. Market direction", f"**Regime: {reg['label']}** (rule score {reg['score']}/{reg['max_score']}). "
              f"{reg['guidance']}"]
    lines += [f"- {'✅' if ok else '❌'} {name}" for name, ok in reg["rules"]]
    idx = mc["indices"]
    if len(idx):
        lines += ["", "| Index | Last | 1D | 1W | 1M | YTD |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['Name']} | {r['Last']:,.2f} | {_fmt(r['1D %'], '%')} | {_fmt(r['1W %'], '%')} | "
                  f"{_fmt(r['1M %'], '%')} | {_fmt(r['YTD %'], '%')} |" for _, r in idx.iterrows()]
    b = mc.get("breadth", {})
    if b.get("stocks"):
        lines += ["", f"Breadth (scan-universe proxy, {b['stocks']} stocks): {b['advancers']} up / {b['decliners']} down; "
                  f"{b['pct_above_50dma']}% above 50DMA; {b.get('pct_above_200dma')}% above 200DMA."]
    sec = mc["sectors"]
    if len(sec):
        lines += ["", "## 2–3. Sector leadership (3M relative strength vs SPY)"]
        lines += ["- Strongest: " + ", ".join(f"{r['Name']} ({r['Symbol']} {r['RS vs SPY 3M (pp)']:+.1f}pp)"
                                                for _, r in sec.head(3).iterrows())]
        lines += ["- Weakest: " + ", ".join(f"{r['Name']} ({r['Symbol']} {r['RS vs SPY 3M (pp)']:+.1f}pp)"
                                              for _, r in sec.tail(3).iterrows())]
    macro = mc.get("macro")
    if macro is not None and len(macro):
        lines += ["", "## 4. Macro (FRED, latest observation dates shown)"]
        lines += [f"- {r['Indicator']}: {r['Latest']:,} {r['Unit']} (prev {r['Previous']:,}; obs {r['Observation date']})"
                  for _, r in macro.iterrows()]
        lines += [f"- {s}" for s in mc.get("recession_signals", [])]
    geo = mc.get("news_macro_geo")
    if geo is not None and len(geo):
        lines += ["", "## 5. Macro & geopolitical headlines (last 3 days)"] + news_lines(geo, 12)
    ev = mc.get("upcoming_events")
    lines += ["", "## 6. Upcoming catalysts"]
    if ev is not None and len(ev):
        lines += [f"- {r['date']}: {r['event']} ({r['importance']})" for _, r in ev.iterrows()]
    else:
        lines += ["- No events recorded. Add FOMC / CPI / jobs dates in the Earnings Calendar page."]
    scan, run_at, as_of = latest_scan()
    lines += ["", "## 7. Potential opportunities (latest scan)"]
    if run_at is None:
        lines += ["- No scan has been run."]
    elif scan.empty:
        lines += [f"- Scan at {run_at:%Y-%m-%d %H:%M} UTC found no qualifying setups."]
    else:
        lines += [f"- **{r['Ticker']}** ({r['Sector']}) score {r['Score']} — {r['Setup']}; risks: {r['Risks']}"
                  for _, r in scan.head(8).iterrows()]
        lines += [f"_Scan {run_at:%Y-%m-%d %H:%M} UTC, data as of {as_of}. Scores are rule points, not probabilities._"]
    lines += ["", "## 8. Risks to watch"]
    risks = []
    if reg.get("vix") and reg["vix"] > 20:
        risks.append(f"VIX elevated at {reg['vix']:.1f}.")
    if b.get("pct_above_50dma") is not None and b["pct_above_50dma"] < 50:
        risks.append(f"Weak participation: only {b['pct_above_50dma']}% of universe above 50DMA.")
    risks += [s for s in mc.get("recession_signals", []) if "≥0.50" in s or "inverted" in s or "elevated" in s]
    lines += [f"- {r}" for r in risks] or ["- No rule-based risk flags triggered (does not mean low risk)."]
    return "\n".join(lines)


def ai_payload(mc: dict) -> dict:
    keep = ["generated_at_utc", "market_status_now", "indices", "index_data_meta", "sectors", "breadth", "regime",
            "spy_volume_trend", "macro", "recession_signals", "upcoming_events"]
    p = {k: mc.get(k) for k in keep}
    for k in ("news_macro_geo", "news_markets"):
        df = mc.get(k)
        if df is not None and len(df):
            p[k] = df[["published_utc", "headline", "source", "url", "category", "info_type", "impact"]].head(25)
    scan, run_at, as_of = latest_scan()
    if run_at is not None and len(scan):
        p["latest_scan"] = {"run_at_utc": run_at, "data_as_of": as_of,
                            "top": scan.head(10)[["Ticker", "Sector", "Score", "Setup", "Risks", "Earnings flag"]]}
    return p
