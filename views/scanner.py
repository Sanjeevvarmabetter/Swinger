"""Stock Scanner — Institutional Stock Discovery Workstation."""
from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import streamlit as st

from tradingos import watchlist
from tradingos.analysis.scanner import CATEGORIES, SCORE_DISCLAIMER, latest_scan, run_scan
from tradingos.data.news import query_news
from tradingos.ui import components as ui
from tradingos.ui.state import select_ticker

ui.render_top_bar(show_refresh=False)

st.markdown("## Stock Scanner")
st.caption("Discovery across liquid US equities and ETFs · " + SCORE_DISCLAIMER)

base = ui.settings()

# Controls row
with st.expander("Filter & Screening Parameters", expanded=False):
    f1, f2, f3, f4 = st.columns(4)
    min_price = f1.number_input("Min Price ($)", 1.0, 2000.0, float(base.min_price), 1.0)
    min_dv = f1.number_input("Min Avg $ Vol (M)", 1.0, 5000.0, float(base.min_avg_dollar_volume_m), 5.0)
    rsi_rng = f2.slider("RSI Momentum Band", 15, 95, (int(base.rsi_min), int(base.rsi_max)))
    req200 = f2.checkbox("Require Price > 200DMA", base.require_above_200dma)
    rv_b = f3.number_input("Breakout Rel Volume >=", 1.0, 5.0, float(base.rel_volume_breakout), 0.1)
    rv_u = f3.number_input("Unusual Rel Volume >=", 1.2, 10.0, float(base.rel_volume_unusual), 0.1)
    lb = f4.number_input("Breakout Lookback (days)", 10, 252, int(base.breakout_lookback))
    rs_lb = f4.number_input("RS Lookback (days)", 10, 252, int(base.rs_lookback_days))

cfg = replace(
    base,
    min_price=min_price,
    min_avg_dollar_volume_m=min_dv,
    rsi_min=float(rsi_rng[0]),
    rsi_max=float(rsi_rng[1]),
    require_above_200dma=req200,
    rel_volume_breakout=rv_b,
    rel_volume_unusual=rv_u,
    breakout_lookback=int(lb),
    rs_lookback_days=int(rs_lb),
)

act_col1, act_col2, _ = st.columns([1.2, 1.2, 3])
with act_col1:
    run_btn = st.button("▶ Run Full Market Scan", type="primary", width="stretch")
with act_col2:
    force = st.checkbox("Force Fresh Data", help="Bypass 15m price cache")

if run_btn:
    with st.spinner("Downloading 1y price histories & executing deterministic screening..."):
        out = run_scan(cfg, force=force)
    st.session_state["scan_out"] = {
        "cands": out.candidates,
        "cats": out.categories,
        "meta": out.data.meta(),
        "universe": out.universe_size,
        "evaluated": out.evaluated,
        "excluded": out.excluded,
        "run_at": out.run_at,
    }

res = st.session_state.get("scan_out")
if res is None:
    cands, run_at, as_of = latest_scan()
    if run_at is None:
        ui.empty_state("No scan has been run yet. Click '▶ Run Full Market Scan' to initiate.")
        st.stop()
    st.caption(f"Displaying saved scan from {run_at:%Y-%m-%d %H:%M} UTC (Data as of {as_of}). Run scan to refresh.")
    cats = {
        k: list(cands.loc[cands["Categories"].str.split(",").apply(lambda c, k=k: k in c), "Ticker"])
        if len(cands) else []
        for k in CATEGORIES
    }
else:
    cands, cats = res["cands"], res["cats"]
    ui.freshness_badge(res["meta"], "Prices")
    ex = res["excluded"]
    st.caption(
        f"Universe {res['universe']} · Evaluated {res['evaluated']} · Excluded: "
        + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in ex.items() if v)
    )

if cands is None or cands.empty:
    ui.empty_state("No candidates met screening criteria. Cash is a valid position.")
    st.stop()

# Search and Sector filter toolbar
s1, s2 = st.columns([2, 2])
with s1:
    search_q = st.text_input("Filter by Symbol or Company", placeholder="e.g. NVDA, Apple, Tech...").strip().lower()
with s2:
    all_sectors = ["All"] + sorted([s for s in cands["Sector"].dropna().unique() if s])
    selected_sec = st.selectbox("Filter by Sector", all_sectors)

# Preset tabs
PRESETS = [
    ("all", "All Qualified"),
    ("momentum", "Strong Uptrends"),
    ("breakout", "Breakout Candidates"),
    ("pullback", "Pullback Opportunities"),
    ("unusual_volume", "High Rel Volume"),
    ("high_rs", "RS Leaders"),
    ("earnings", "Earnings Momentum"),
    ("sector_leaders", "Sector Leaders"),
]

preset_tabs = st.tabs([f"{label} ({len(cats.get(key, cands)) if key != 'all' else len(cands)})" for key, label in PRESETS])

# Format dataframe for display
display_cols = [
    "Ticker", "Company", "Sector", "Price", "1D %", "1W %", "1M %", "RSI", "Rel vol",
    "Score", "Trend", "Setup", "Next earnings"
]
avail_cols = [c for c in display_cols if c in cands.columns]

for tab, (pkey, plabel) in zip(preset_tabs, PRESETS):
    with tab:
        df_view = cands if pkey == "all" else cands[cands["Ticker"].isin(cats.get(pkey, []))]

        if selected_sec != "All":
            df_view = df_view[df_view["Sector"] == selected_sec]

        if search_q:
            df_view = df_view[
                df_view["Ticker"].str.lower().str.contains(search_q)
                | df_view["Company"].str.lower().str.contains(search_q)
            ]

        if df_view.empty:
            ui.empty_state(f"No candidates matching '{plabel}' under current filters.")
        else:
            st.dataframe(
                df_view[avail_cols],
                hide_index=True,
                width="stretch",
                height=420,
                column_config={
                    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                    "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "1D %": st.column_config.NumberColumn("1D %", format="%+.2f%%"),
                    "1W %": st.column_config.NumberColumn("1W %", format="%+.2f%%"),
                    "1M %": st.column_config.NumberColumn("1M %", format="%+.2f%%"),
                },
            )

st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
st.markdown("### Candidate Research & Verification")

pick = st.selectbox("Select Candidate for In-Depth Review", list(cands["Ticker"]), key="_scanner_pick")
if pick:
    row = cands[cands["Ticker"] == pick].iloc[0]
    score_val = row["Score"]
    score_badge = ui.badge(f"Score {score_val}/100", "green" if score_val >= 60 else "blue")
    cd1, cd2 = st.columns([1.2, 1])

    with cd1:
        st.markdown(
            f'<div class="term-card">'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
            f'    <span style="font-size:1.15rem;font-weight:700;color:#F8FAFC;">{row["Ticker"]} — {row["Company"]}</span>'
            f'    {score_badge}'
            f'  </div>'
            f'  <div style="font-size:0.80rem;color:#94A3B8;margin-top:6px;">'
            f'    <strong>Sector:</strong> {row["Sector"]} · <strong>Setup:</strong> {row["Setup"]}'
            f'  </div>'
            f'  <div style="font-size:0.80rem;color:#CBD5E1;margin-top:4px;">'
            f'    <strong>Setup Rationale:</strong> {row["Reason"]}'
            f'  </div>'
            f'  <div style="font-size:0.80rem;color:#F43F5E;margin-top:4px;">'
            f'    <strong>Risks:</strong> {row["Risks"]}'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        with st.expander("Score Breakdown by Criteria", expanded=False):
            if "Score breakdown" in row and row["Score breakdown"]:
                bd = json.loads(row["Score breakdown"])
                st.dataframe(pd.DataFrame([bd]), hide_index=True, width="stretch")

    with cd2:
        st.markdown("**Recent News & Catalysts**")
        news = query_news(days=14, ticker=pick)
        if news.empty:
            ui.empty_state("No recent news stored for this symbol.")
        else:
            for _, n in news.head(4).iterrows():
                pub = n.get("published_utc")
                pub_str = f" · {pd.Timestamp(pub):%Y-%m-%d %H:%M} UTC" if pub and pd.notna(pub) else ""
                st.markdown(f"- [{n['headline']}]({n['url']}) <span style='font-size:0.75rem;color:#64748B;'>{n['source']}{pub_str}</span>", unsafe_allow_html=True)

    # Action Toolbar
    act1, act2, act3, act4 = st.columns(4)
    with act1:
        if st.button("📊 Technical Analysis", width="stretch"):
            select_ticker(pick)
            st.switch_page("views/technical.py")
    with act2:
        if st.button("✨ AI Institutional Research", width="stretch"):
            select_ticker(pick)
            st.switch_page("views/ai_analyst.py")
    with act3:
        if st.button("🎯 Build Trade Plan", width="stretch"):
            select_ticker(pick)
            st.session_state["plan_setup_hint"] = row["Setup"]
            st.switch_page("views/trade_planner.py")
    with act4:
        if st.button("👁️ Add to Watchlist", width="stretch"):
            watchlist.add(pick, notes=f"From scan: {row['Setup']}")
            st.toast(f"{pick} added to Watchlist.")

st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
ui.disclaimer()
