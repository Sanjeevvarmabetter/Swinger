import pandas as pd
import streamlit as st

from tradingos import briefing
from tradingos.ai import gemini
from tradingos.config import load_config
from tradingos.data.macro import MACRO_SERIES, get_series
from tradingos.data.providers import INDEX_SYMBOLS, get_market_provider
from tradingos.ui import charts, components as ui
from tradingos.ui.state import market_ctx, refresh_market

ui.render_top_bar(show_refresh=True)

st.markdown("## Market Intelligence & Macro Dashboard")
st.caption("Cross-asset market trends · 11 S&P sectors relative strength · FRED macroeconomic series · Geopolitical risk tracking")

with st.spinner("Loading indices, sectors, breadth and macro data…"):
    mc = market_ctx(include_macro=True)

tab_mkt, tab_sec, tab_macro, tab_geo, tab_report = st.tabs(
    ["Indices & regime", "Sectors", "Macro", "Geopolitics & macro news", "Daily report"])

with tab_mkt:
    ui.freshness_badge(mc["index_data_meta"], "Indices")
    idx = mc["indices"]
    if len(idx):
        st.dataframe(ui.color_pct_cols(idx, ["1D %", "1W %", "1M %", "3M %", "YTD %"]), hide_index=True,
                     width="stretch")
        res = get_market_provider().history(list(INDEX_SYMBOLS.values()), period="6mo")
        if res.ok:
            series = {}
            for name, sym in INDEX_SYMBOLS.items():
                if sym in res.data:
                    c = res.data[sym]["Close"]
                    series[name] = (c / c.iloc[0] - 1) * 100
            st.plotly_chart(charts.line_chart(series, "Index performance, last 6 months (%)", 330),
                            width="stretch")
    reg = mc["regime"]
    st.subheader(f"Regime: {reg['label']}")
    st.caption(reg["guidance"] + " Regime is a transparent rule checklist, not a forecast.")
    st.table(pd.DataFrame([{"Rule": n, "Passed": "✅" if ok else "❌"} for n, ok in reg["rules"]]))
    b = mc["breadth"]
    if b.get("stocks"):
        cols = st.columns(5)
        cols[0].metric("Advancers / decliners", f"{b['advancers']} / {b['decliners']}")
        cols[1].metric("% above 50DMA", f"{b['pct_above_50dma']}%")
        cols[2].metric("% above 200DMA", f"{b['pct_above_200dma']}%")
        cols[3].metric("New 52w highs", b["new_52w_highs"])
        cols[4].metric("New 52w lows", b["new_52w_lows"])
        st.caption(b["note"])
    vt = mc.get("spy_volume_trend")
    if vt:
        st.caption(f"SPY volume: today {vt['rel_volume_today']}× 20-day avg; 20d/50d avg volume ratio "
                   f"{vt['avg_vol_20d_vs_50d']}.")

with tab_sec:
    sec = mc["sectors"]
    ui.freshness_badge(mc["sector_data_meta"], "Sector ETFs")
    if len(sec):
        a, b_ = st.columns(2)
        a.plotly_chart(charts.bar_chart(sec, "Name", "RS vs SPY 3M (pp)", "3-month relative strength vs SPY (pp)"),
                       width="stretch")
        b_.plotly_chart(charts.bar_chart(sec, "Name", "1M %", "1-month return (%)"), width="stretch")
        st.dataframe(ui.color_pct_cols(sec, ["1D %", "1W %", "1M %", "3M %", "YTD %", "RS vs SPY 3M (pp)"]),
                     hide_index=True, width="stretch")
    else:
        ui.empty_state("Sector data unavailable.")

with tab_macro:
    macro = mc.get("macro")
    if macro is not None and len(macro):
        st.caption(f"Source: FRED (St. Louis Fed). Retrieved {macro.attrs.get('retrieved_at', '')}. "
                   "Each row shows its own observation date — macro data is released periodically, not live.")
        for grp, g in macro.groupby("Group", sort=False):
            st.markdown(f"**{grp}**")
            st.dataframe(g.drop(columns=["Group"]), hide_index=True, width="stretch",
                         column_config={"Source": st.column_config.LinkColumn("Source")})
        for s in mc.get("recession_signals", []):
            st.markdown(f"- {s}")
        pick = st.selectbox("Chart a series", [m.label for m in MACRO_SERIES])
        ms = next(m for m in MACRO_SERIES if m.label == pick)
        r = get_series(ms)
        if r.ok:
            st.plotly_chart(charts.line_chart({ms.label: r.data}, f"{ms.label} ({ms.unit})", 280),
                            width="stretch")
    if mc.get("macro_errors"):
        st.warning("Some macro series failed to load: " + "; ".join(mc["macro_errors"][:5]))
    st.caption("Fed decisions & statements: federalreserve.gov · CPI/jobs: bls.gov · GDP/PCE: bea.gov "
               "(their press releases appear in News & Catalysts).")

with tab_geo:
    geo = mc.get("news_macro_geo")
    st.caption("Headlines from configured feeds (last 3 days). Impact notes are keyword heuristics — "
               "interpretation, not fact. Refresh feeds on the News & Catalysts page.")
    if geo is None or geo.empty:
        ui.empty_state("No macro/geopolitical headlines stored. Go to News & Catalysts → Refresh news.")
    else:
        for line in briefing.news_lines(geo, 25):
            st.markdown(line)

with tab_report:
    st.markdown("A **deterministic** report is built from the data above. Gemini can add interpretation "
                "using only that same data.")
    report = briefing.deterministic_report(mc)
    with st.expander("Deterministic daily brief", expanded=True):
        st.markdown(report)
    st.download_button("Download brief (.md)", report, file_name="daily_brief.md")
    ui.gemini_panel("market_analysis", "Generate AI market intelligence report",
                    lambda: gemini.market_analysis(briefing.ai_payload(mc)))
    if load_config().ai_configured:
        past = gemini.recent_reports("market_analysis", limit=5)
        if past:
            with st.expander("Previous AI market reports"):
                for r in past:
                    st.markdown(f"**{r.created_at:%Y-%m-%d %H:%M} UTC · {r.model}**")
                    st.markdown(r.output_text)
                    st.divider()
ui.disclaimer()
