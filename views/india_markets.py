"""Indian Markets — indices, cap-size breadth, sectors, India VIX, rupee, global transmission, Indian news."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.intel import markets
from tradingos.intel.instruments import UNAVAILABLE
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=True)
iu.page_header("Indian Market Intelligence", "Nifty · Sensex · Bank Nifty · caps · sectors · India VIX · USD/INR · "
               "global cues — NSE data via Yahoo (delayed; NSE holidays not modelled, flagged as stale)")

df, meta = iu.snapshot()
iu.tiles(df, ["^NSEI", "^BSESN", "^NSEBANK", "^INDIAVIX", "INR=X"], per_row=5, fmt={"INR=X": "₹{:.2f}"})
nifty = markets.row(df, "^NSEI")
if nifty and not markets.is_live_like(nifty["Freshness"]):
    st.warning(f"Indian index data last bar: {nifty['Last bar']} — {nifty['Freshness note']}")

t_over, t_sec, t_global, t_news, t_ai = st.tabs(["Indices & breadth", "Sectors", "Global cues", "Indian news",
                                                 "AI India analyst"])

with t_over:
    india = markets.group(df, "India")
    iu.perf_table(india)
    st.markdown("**Breadth across market caps** (relative to Nifty 50, percentage points)")
    rows = []
    for name, sym in (("Nifty Next 50", "^NSMIDCP"), ("Nifty Midcap 50", "^NSEMDCP50"),
                      ("Nifty Smallcap 250", "NIFTYSMLCAP250.NS"), ("Nifty 500", "^CRSLDX"), ("Bank Nifty", "^NSEBANK")):
        rows.append({"Index": name, **{f"vs Nifty {p}": markets.rel_perf(df, sym, "^NSEI", f"{p} %")
                                       for p in ("1W", "1M", "3M", "YTD")}})
    rel = pd.DataFrame(rows)
    st.dataframe(ui.color_pct_cols(rel, [c for c in rel.columns if c != "Index"]), hide_index=True, width="stretch")
    st.caption("Positive = outperforming the Nifty 50. Mid/small caps leading usually signals broad domestic risk "
               "appetite; lagging signals narrowing or defensive leadership. A comparison, not a forecast.")
    closes = iu.closes()
    st.plotly_chart(iu.rebased_chart(closes, {"^NSEI": "Nifty 50", "^NSEMDCP50": "Midcap 50",
                                              "NIFTYSMLCAP250.NS": "Smallcap 250", "^NSEBANK": "Bank Nifty",
                                              "^GSPC": "S&P 500"}, 365), width="stretch")

with t_sec:
    sec = markets.group(df, "India sectors").drop_duplicates("Symbol")
    c1, c2 = st.columns([1.2, 1])
    c1.plotly_chart(iu.heatmap(sec.sort_values("1W %", ascending=False), title="NSE sector indices — % change"),
                    width="stretch", config=iu.STATIC_CHART)
    with c2:
        ok = sec.dropna(subset=["1M %"]).sort_values("1M %", ascending=False)
        if len(ok):
            st.markdown("**Strongest (1M)**")
            for _, r in ok.head(4).iterrows():
                st.markdown(f"- {r['Name']}: {ui.pct(r['1M %'], 2)} (1W {ui.pct(r['1W %'], 2)})")
            st.markdown("**Weakest (1M)**")
            for _, r in ok.tail(4).iloc[::-1].iterrows():
                st.markdown(f"- {r['Name']}: {ui.pct(r['1M %'], 2)} (1W {ui.pct(r['1W %'], 2)})")
        st.caption("Nifty Defence, Media, Healthcare and Smallcap 100 are omitted: Yahoo history for them was "
                   "empty or single-bar when verified.")

with t_global:
    st.markdown("**How global factors are moving** (common transmission channels to Indian equities)")
    chans = [("US 10Y yield", "^TNX", "Higher US yields tend to pull foreign portfolio money from emerging markets."),
             ("US Dollar Index", "DX-Y.NYB", "A stronger dollar usually pressures EM currencies and FPI flows."),
             ("USD/INR", "INR=X", "A weaker rupee raises import costs (oil) and lowers USD returns for foreign investors."),
             ("Brent crude", "BZ=F", "India imports most of its crude: higher oil widens the deficit and lifts inflation."),
             ("S&P 500", "^GSPC", "Global risk appetite spills over to Indian large caps and IT services."),
             ("Nasdaq 100", "^NDX", "US tech spending sentiment matters for Indian IT exporters."),
             ("Gold", "GC=F", "India is a top gold consumer; gold prices affect jewellers, gold-loan NBFCs and the import bill.")]
    rows = []
    for name, sym, why in chans:
        r = markets.row(df, sym)
        rows.append({"Factor": name, "Last": r["Last"] if r else None, "1D %": r["1D %"] if r else None,
                     "1W %": r["1W %"] if r else None, "1M %": r["1M %"] if r else None,
                     "Last bar": r["Last bar"] if r else None, "Why it matters for India": why})
    g = pd.DataFrame(rows)
    st.dataframe(ui.color_pct_cols(g, ["1D %", "1W %", "1M %"]), hide_index=True, width="stretch")
    risk = iu.risk()
    st.markdown(f"Global cross-asset risk appetite: **{risk['label']}** (see Global Markets for the checklist).")
    iu.unavailable_box([u for u in UNAVAILABLE if "FII" in u[0] or "NSE" in u[0] or "MCX" in u[0]])

with t_news:
    c1, c2 = st.columns([1, 3])
    days = c1.selectbox("Window", [1, 2, 3, 7], index=1, format_func=lambda d: f"Last {d}d")
    ranked = iu.ranked_news(days, "India")
    c2.caption("Indian outlets + RBI official releases. RBI items are tagged [FACT]; routine RBI notices are "
               "down-ranked. SEBI/NSE/BSE filings are not ingested (no authorised feed).")
    iu.story_list(ranked, n=30)

with t_ai:
    payload = {"generated_at_utc": iu.utc_now_str(),
               "india_indices": markets.group(df, "India")[["Name", "Last", "1D %", "1W %", "1M %", "YTD %", "Last bar", "Freshness", "Freshness note"]],
               "india_sectors": markets.group(df, "India sectors").drop_duplicates("Symbol")[["Name", "1D %", "1W %", "1M %", "YTD %"]],
               "cap_relative_performance_vs_nifty": rel, "global_factors": g, "global_risk_appetite": risk,
               "news": iu.ranked_news(2, "India").head(30)[["tier", "headline", "source", "published_utc", "url", "info_type", "topics"]],
               "not_available": ["FII/DII daily flows", "NSE/BSE corporate announcements", "bulk/block deals",
                                 "MCX prices", "Indian macro calendar (RBI MPC dates must be added manually)"]}
    ui.gemini_panel("india_analyst", "Explain the Indian market environment",
                    lambda: gemini.intel_analysis("india_market_analyst", payload, "India"),
                    payload_for_links=payload)

ui.disclaimer()
