"""Gold & Commodities Intelligence Centre — drivers, positioning, INR gold, metals & energy."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from tradingos.ai import gemini
from tradingos.intel import gold, markets
from tradingos.intel.instruments import UNAVAILABLE
from tradingos.ui import charts
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=True)
iu.page_header("Gold & Commodities Intelligence", "Why gold is moving (rule-based driver checks) · positioning · "
               "INR gold · silver, copper, oil, gas — every number sourced and dated")

df, meta = iu.snapshot()
closes = iu.closes()


@st.cache_data(ttl=1800, show_spinner=False)
def _gold_ctx(nonce: int) -> dict:  # noqa: ARG001
    return gold.gold_context(df, closes)


with st.spinner("Loading FRED real yields, breakevens and CFTC positioning…"):
    gc = _gold_ctx(st.session_state.get("mkt_nonce", 0))

iu.tiles(df, ["GC=F", "SI=F", "HG=F", "BZ=F", "NG=F"], per_row=5)
chips = []
if gc.get("gold_inr_per_10g", {}).get("value"):
    chips.append(ui.chip(f"≈ ₹{gc['gold_inr_per_10g']['value']:,.0f} / 10 g (converted, not MCX)", "tos-amber"))
if gc.get("gold_silver_ratio"):
    chips.append(ui.chip(f"Gold/silver ratio {gc['gold_silver_ratio']}"))
if gc.get("real_yield_10y"):
    chips.append(ui.chip(f"10Y real yield {gc['real_yield_10y']['value']:.2f}% ({gc['real_yield_10y']['as_of']})"))
if gc.get("breakeven_10y"):
    chips.append(ui.chip(f"10Y breakeven {gc['breakeven_10y']['value']:.2f}% ({gc['breakeven_10y']['as_of']})"))
st.markdown(" ".join(chips), unsafe_allow_html=True)
if gc.get("gold_inr_per_10g"):
    st.caption(gc["gold_inr_per_10g"]["basis"])
for e in gc.get("errors", []):
    st.warning(e)

t_why, t_pos, t_chart, t_cmd, t_news, t_ai = st.tabs(["Why is gold moving?", "Positioning (CFTC)", "Charts",
                                                      "All commodities", "News", "AI gold analyst"])

with t_why:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Short term (≈1 month)")
        st.info(gc.get("reading_1m", "Insufficient data."))
        if gc.get("drivers_1m"):
            st.dataframe(pd.DataFrame(gc["drivers_1m"]), hide_index=True, width="stretch")
    with c2:
        st.markdown("#### Long term (≈1 year)")
        st.info(gc.get("reading_1y", "Insufficient data."))
        if gc.get("drivers_1y"):
            st.dataframe(pd.DataFrame(gc["drivers_1y"]), hide_index=True, width="stretch")
    s = gc.get("structure") or {}
    if s:
        st.markdown(f"**Structure:** {'above' if s.get('above_200dma') else 'below'} the 200-day average "
                    f"({s.get('pct_from_200dma'):+.1f}%) · {s.get('pct_from_52w_high'):+.1f}% from the 52-week high.")
    st.caption("Method: for each conventional driver, the change over the window is compared with the direction that "
               "is usually gold-supportive; '60d corr' is the correlation of daily gold returns with daily driver "
               "changes over ~60 sessions (negative for DXY/real yields = the textbook relationship is holding). "
               "This shows consistency, not causation. Investment demand, central-bank buying and geopolitical "
               "hedging are NOT measured here.")
    iu.unavailable_box([u for u in UNAVAILABLE if "gold" in u[0].lower() or "MCX" in u[0]])

with t_pos:
    contract = st.selectbox("Contract", list(gold.CFTC_CODES))
    pos = gold.cftc_positioning(gold.CFTC_CODES[contract], weeks=156)
    if pos.ok:
        summ = gold.positioning_summary(pos.data)
        c = st.columns(4)
        c[0].metric("Managed money net", f"{summ['mm_net']:,}", f"{summ['weekly_change']:+,} w/w")
        c[1].metric("Net % of open interest", f"{summ['net_pct_open_interest']}%")
        c[2].metric("Percentile (3y window)", f"{summ['percentile_in_window']:.0f}")
        c[3].metric("Report date", summ["as_of"])
        st.markdown(f"**Reading:** {summ['reading']}")
        d = pos.data
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=d["date"], y=d["mm_net"], name="Managed money net (contracts)",
                             marker_color=["#10B981" if v >= 0 else "#F43F5E" for v in d["mm_net"]]))
        fig.add_trace(go.Scatter(x=d["date"], y=d["open_interest_all"], name="Open interest",
                                 line=dict(color="#94A3B8", width=1)), secondary_y=True)
        fig.update_layout(title=dict(text=f"{contract} — CFTC managed-money positioning", x=0.01, font=dict(size=12)))
        st.plotly_chart(charts._layout(fig, 340), width="stretch")
        st.caption(f"Source: {pos.source}. {pos.notes}")
    else:
        st.error(pos.error)

with t_chart:
    g = closes.get("GC=F")
    real = gold.macro_drivers()["real_yield"]
    if g is not None and real.ok:
        win = st.select_slider("Window", [90, 180, 365, 730], value=365, format_func=lambda d: f"{d}d")
        gs = g[g.index >= g.index[-1] - pd.Timedelta(days=win)]
        rs = real.data[real.data.index >= gs.index[0]]
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=gs.index, y=gs.values, name="Gold (USD/oz)", line=dict(color="#F59E0B", width=1.8)))
        fig.add_trace(go.Scatter(x=rs.index, y=rs.values, name="10Y real yield (%, inverted)",
                                 line=dict(color="#38BDF8", width=1.4)), secondary_y=True)
        fig.update_yaxes(autorange="reversed", secondary_y=True)
        fig.update_layout(title=dict(text="Gold vs 10Y real yield (right axis inverted)", x=0.01, font=dict(size=12)))
        st.plotly_chart(charts._layout(fig, 360), width="stretch")
    st.plotly_chart(iu.rebased_chart(closes, {"GC=F": "Gold", "SI=F": "Silver", "HG=F": "Copper", "BZ=F": "Brent",
                                              "GDX": "Gold miners", "DX-Y.NYB": "Dollar index"}, 365), width="stretch")

with t_cmd:
    iu.perf_table(pd.concat([markets.group(df, "Precious metals"), markets.group(df, "Gold proxies"),
                             markets.group(df, "Energy & industrial")]))
    cg = markets.rel_perf(df, "HG=F", "GC=F")
    if cg is not None:
        st.markdown(f"- Copper vs gold (1M): **{cg:+.2f} pp** — copper outperforming gold is usually read as growth "
                    "optimism; the reverse as caution.")
    oil = markets.row(df, "BZ=F")
    if oil:
        st.markdown(f"- Brent {oil['Last']:.2f} USD/bbl, 1M {ui.pct(oil['1M %'], 2)} — relevant for India's import bill "
                    "and inflation, airlines, paints, OMCs.")

with t_news:
    ranked = iu.ranked_news(3)
    if len(ranked):
        sub = ranked[ranked["topics"].str.contains("Gold|Oil", na=False) | (ranked["category"] == "commodities")]
        iu.story_list(sub, n=30, tiers=("MUST KNOW", "IMPORTANT", "INTERESTING", "IGNORE FOR NOW"))
    else:
        ui.empty_state("No commodity news stored.")

with t_ai:
    payload = {"generated_at_utc": iu.utc_now_str(), "gold_context": gc,
               "commodities": pd.concat([markets.group(df, "Precious metals"), markets.group(df, "Energy & industrial"),
                                         markets.group(df, "Gold proxies")])[["Name", "Last", "1D %", "1W %", "1M %", "YTD %", "1Y %", "Last bar", "Freshness"]],
               "dollar_and_rates": pd.concat([markets.group(df, "Currencies"), markets.group(df, "US Treasury yields")])[
                   ["Name", "Last", "1W %", "1M %", "Last bar"]],
               "risk_appetite": iu.risk(),
               "news": (iu.ranked_news(3).pipe(lambda r: r[r["topics"].str.contains("Gold|Oil", na=False)]).head(25)
                        [["tier", "headline", "source", "published_utc", "url", "info_type"]] if len(iu.ranked_news(3)) else []),
               "not_measured": ["Gold ETF flows", "Central-bank purchases", "India/China physical demand", "MCX prices"]}
    ui.gemini_panel("gold_analyst", "Explain what is driving gold",
                    lambda: gemini.intel_analysis("gold_analyst", payload, "gold"))

ui.disclaimer()
