"""Global Markets — cross-asset dashboard: indices, rates, FX, commodities, risk appetite."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.intel import markets
from tradingos.intel.instruments import groups
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=True)
iu.page_header("Global Markets", "World indices, rates, currencies and commodities with exchange-aware freshness · "
               "transparent cross-asset risk-appetite checklist")

df, meta = iu.snapshot()
iu.meta_line(meta)
risk = iu.risk()

tab_over, tab_risk, tab_tables, tab_chart, tab_ai = st.tabs(
    ["Overview heatmap", "Risk-on / risk-off", "All instruments", "Charts", "AI macro analyst"])

CORE = ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "^TNX", "DX-Y.NYB", "EURUSD=X", "JPY=X", "INR=X", "^FTSE", "^GDAXI",
        "^N225", "^HSI", "000001.SS", "^NSEI", "^NSEBANK", "^BSESN", "GC=F", "SI=F", "CL=F", "HG=F", "NG=F"]

with tab_over:
    core = df[df["Symbol"].isin(CORE)].drop_duplicates("Symbol").set_index("Symbol").loc[
        [s for s in CORE if s in set(df["Symbol"])]].reset_index()
    a, b = st.columns([1.15, 1])
    with a:
        st.plotly_chart(iu.heatmap(core, title="Core markets — % change (yields: % change of the yield level)"),
                        width="stretch")
    with b:
        st.markdown("**Regional scoreboard (1W %)**")
        reg = {"US": ["^GSPC", "^NDX", "^RUT"], "Europe": ["^FTSE", "^GDAXI", "^STOXX50E"],
               "Asia": ["^N225", "^HSI", "000001.SS", "^KS11"], "India": ["^NSEI", "^BSESN", "^NSEBANK"]}
        rows = []
        for region, syms in reg.items():
            vals = [markets.row(df, s) for s in syms]
            vals = [v for v in vals if v and v.get("1W %") is not None and pd.notna(v["1W %"])]
            if vals:
                rows.append({"Region": region, "Avg 1W %": round(sum(v["1W %"] for v in vals) / len(vals), 2),
                             "Avg 1M %": round(sum((v["1M %"] or 0) for v in vals) / len(vals), 2),
                             "Indices": ", ".join(v["Name"] for v in vals)})
        st.dataframe(pd.DataFrame(rows).sort_values("Avg 1W %", ascending=False), hide_index=True, width="stretch",
                     column_config={"Avg 1W %": st.column_config.NumberColumn(format="%+.2f"),
                                    "Avg 1M %": st.column_config.NumberColumn(format="%+.2f")})
        st.caption("Simple average of each region's listed indices — a quick divergence gauge, not an index.")
        iu.tiles(df, ["^GSPC", "^NSEI", "GC=F", "DX-Y.NYB"], per_row=2)

with tab_risk:
    cls = {"Risk-on": "tos-green", "Risk-off": "tos-red", "Mixed": "tos-amber"}.get(risk["label"], "")
    st.markdown(f"### {ui.chip(risk['label'], cls)} &nbsp; {risk['risk_on']} risk-on · {risk['risk_off']} risk-off · "
                f"{len(risk['signals']) - risk['risk_on'] - risk['risk_off']} neutral", unsafe_allow_html=True)
    sig = pd.DataFrame(risk["signals"])
    if len(sig):
        st.dataframe(sig.style.map(lambda v: "color:#10B981" if v == "Risk-on" else "color:#F43F5E" if v == "Risk-off"
                                   else "", subset=["Reading"]), hide_index=True, width="stretch")
    st.caption(risk["methodology"])
    st.markdown("**Volatility & credit**")
    iu.perf_table(pd.concat([markets.group(df, "Volatility"), markets.group(df, "Credit & bonds")]))

with tab_tables:
    pick = st.multiselect("Groups", groups(), default=["US indices", "Europe", "Asia-Pacific", "India",
                                                       "US Treasury yields", "Currencies", "Precious metals",
                                                       "Energy & industrial"])
    for g in pick:
        st.markdown(f"**{g}**")
        iu.perf_table(markets.group(df, g))
    st.caption("Yields (^IRX/^FVX/^TNX/^TYX) are quoted in percent; their % change columns are relative changes of "
               "the yield level. USD/JPY and USD/INR rising = dollar strengthening.")

with tab_chart:
    closes = iu.closes()
    options = {f"{r['Name']} ({r['Symbol']})": r["Symbol"] for _, r in df.drop_duplicates("Symbol").iterrows()
               if r["Symbol"] in closes}
    default = [k for k in options if options[k] in ("^GSPC", "^NSEI", "^N225", "^GDAXI", "GC=F")]
    sel = st.multiselect("Compare (rebased %)", list(options), default=default)
    days = st.select_slider("Window", [30, 90, 180, 365, 730], value=180, format_func=lambda d: f"{d}d")
    if sel:
        st.plotly_chart(iu.rebased_chart(closes, {options[k]: k for k in sel}, days), width="stretch")
    st.caption("Daily closes; each line rebased to 0% at the window start. Different exchanges close at different "
               "times and have different holidays.")

with tab_ai:
    payload = {"generated_at_utc": iu.utc_now_str(), "market_data_meta": meta, "risk_appetite": risk,
               **{g: markets.group(df, g)[["Name", "Last", "1D %", "1W %", "1M %", "YTD %", "Last bar", "Freshness"]]
                  for g in ("US indices", "Volatility", "US Treasury yields", "Credit & bonds", "Currencies", "Europe",
                            "Asia-Pacific", "India", "Precious metals", "Energy & industrial")},
               "news": iu.ranked_news(2).head(30)[["tier", "headline", "source", "published_utc", "url", "region",
                                                   "info_type", "topics"]]}
    ui.gemini_panel("global_macro", "Explain the global macro picture",
                    lambda: gemini.intel_analysis("global_macro_analyst", payload, "global"))

ui.disclaimer()
