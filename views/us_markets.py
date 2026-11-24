"""US Markets — indices, breadth, sectors & themes, rates/credit, calendars, US news, AI analyst."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.intel import calendars, markets
from tradingos.intel.instruments import MAG7, UNAVAILABLE
from tradingos.ui import charts
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu
from tradingos.ui.state import market_ctx

ui.render_top_bar(show_refresh=True)
iu.page_header("US Market Intelligence", "Trend, breadth, sector & theme leadership, rates and credit, catalysts — "
               "NYSE-calendar freshness on every number")

df, meta = iu.snapshot()
with st.spinner("Loading breadth, regime and FRED macro…"):
    mc = market_ctx(include_macro=True)

iu.tiles(df, ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX"], per_row=5)
reg = mc["regime"]
b = mc.get("breadth", {})
st.markdown(
    f'{ui.chip("US regime: " + reg["label"], "tos-blue")} {ui.chip(f"rule score {reg["score"]}/{reg["max_score"]}")} '
    + (f'{ui.chip(f"{b["pct_above_50dma"]}% of universe > 50DMA")} {ui.chip(f"A/D {b["advancers"]}/{b["decliners"]}")}'
       if b.get("stocks") else ui.chip("breadth unavailable", "tos-amber")),
    unsafe_allow_html=True)

t_sec, t_breadth, t_rates, t_cal, t_news, t_ai = st.tabs(
    ["Sectors & themes", "Breadth & regime", "Rates, credit & macro", "Earnings · IPOs · data calendar",
     "US news", "AI US analyst"])

with t_sec:
    sec = markets.group(df, "US sectors")
    thm = markets.group(df, "US themes")
    c1, c2 = st.columns(2)
    c1.plotly_chart(iu.heatmap(sec.sort_values("1W %", ascending=False), title="S&P sector ETFs — % change"),
                    width="stretch", config=iu.STATIC_CHART)
    c2.plotly_chart(iu.heatmap(thm.sort_values("1W %", ascending=False), title="Themes (ETF proxies) — % change"),
                    width="stretch", config=iu.STATIC_CHART)
    st.markdown("**Relative strength vs S&P 500 (3M, pp)**")
    if len(mc["sectors"]):
        st.plotly_chart(charts.bar_chart(mc["sectors"], "Name", "RS vs SPY 3M (pp)", "3-month relative strength vs SPY"),
                        width="stretch")
    st.markdown("**Magnificent 7**")
    m7 = markets.group(df, "Magnificent 7")
    iu.perf_table(m7)
    if len(m7.dropna(subset=["1M %"])):
        spx = markets.row(df, "^GSPC")
        avg = m7["1M %"].astype(float).mean()
        st.caption(f"Equal-weight Mag 7 average 1M: {avg:+.2f}% vs S&P 500 {ui.pct(spx['1M %'], 2) if spx else 'n/a'}. "
                   "Theme ETFs are proxies for the theme, not the theme itself.")

with t_breadth:
    st.markdown(f"**Regime: {reg['label']}** — {reg['guidance']}")
    st.table(pd.DataFrame([{"Rule": n, "Passed": "✅" if ok else "❌"} for n, ok in reg["rules"]]))
    if b.get("stocks"):
        cols = st.columns(5)
        cols[0].metric("Advancers / decliners", f"{b['advancers']} / {b['decliners']}")
        cols[1].metric("% > 20DMA", f"{b['pct_above_20dma']}%")
        cols[2].metric("% > 50DMA", f"{b['pct_above_50dma']}%")
        cols[3].metric("% > 200DMA", f"{b['pct_above_200dma']}%")
        cols[4].metric("52w highs / lows", f"{b['new_52w_highs']} / {b['new_52w_lows']}")
        st.caption(b["note"])
    rsp = markets.rel_perf(df, "RSP", "^GSPC")
    rut = markets.rel_perf(df, "^RUT", "^GSPC")
    st.markdown(f"- Equal-weight vs cap-weight S&P (1M): **{rsp:+.2f} pp**" if rsp is not None else "- RSP vs SPX: n/a")
    st.markdown(f"- Russell 2000 vs S&P 500 (1M): **{rut:+.2f} pp**" if rut is not None else "- RUT vs SPX: n/a")
    st.caption("Exchange-wide advance/decline and institutional flow data are not available from current sources.")

with t_rates:
    iu.perf_table(pd.concat([markets.group(df, "US Treasury yields"), markets.group(df, "Credit & bonds"),
                             markets.group(df, "Volatility")]))
    macro = mc.get("macro")
    if macro is not None and len(macro):
        st.markdown("**FRED macro dashboard** (each row has its own observation date — periodic releases, not live)")
        st.dataframe(macro, hide_index=True, width="stretch",
                     column_config={"Source": st.column_config.LinkColumn("Source", display_text="FRED ↗")})
        for s in mc.get("recession_signals", []):
            st.markdown(f"- {s}")
    if mc.get("macro_errors"):
        st.warning("Some FRED series failed: " + "; ".join(mc["macro_errors"][:4]))
    st.caption("Fed funds futures / market-implied rate path: not available (CME FedWatch has no free API). "
               "[CME FedWatch ↗](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html)")

with t_cal:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**US economic releases (next 21 days, IST)**")
        rel = calendars.us_release_calendar(21)
        if rel.ok and len(rel.data):
            st.dataframe(rel.data[["date", "time_ist", "event", "importance", "source"]], hide_index=True,
                         width="stretch", column_config={"source": st.column_config.LinkColumn("Source", display_text="FRED ↗")})
            st.caption(rel.notes)
        else:
            st.warning(rel.error or "No releases found.")
    with c2:
        st.markdown("**IPOs (Finnhub, last 7 days + next 30)**")
        ipo = calendars.ipo_calendar(30)
        if ipo.ok and len(ipo.data):
            st.dataframe(ipo.data, hide_index=True, width="stretch")
        else:
            ui.empty_state(ipo.error or "No IPOs listed in the window by Finnhub.")
    st.markdown("**Earnings — next 7 days**")
    only_known = st.toggle("Only tracked large caps (breadth universe and Mag 7)", value=True)
    symbols = None
    if only_known:
        from tradingos.data.providers import load_universe
        symbols = set(load_universe()["ticker"]) | set(MAG7.values())
    earn = calendars.earnings_calendar(7, symbols)
    if earn.ok and len(earn.data):
        st.dataframe(earn.data, hide_index=True, width="stretch",
                     column_config={"revenue_estimate": st.column_config.NumberColumn(format="%.3e")})
        st.caption(f"Source: {earn.source}. {earn.notes}")
    else:
        ui.empty_state(earn.error or "No earnings in the window.")

with t_news:
    iu.story_list(iu.ranked_news(2, "US"), n=25)

with t_ai:
    payload = {"generated_at_utc": iu.utc_now_str(), "regime": reg, "breadth": b, "risk_appetite": iu.risk(),
               "indices": markets.group(df, "US indices")[["Name", "Last", "1D %", "1W %", "1M %", "YTD %", "Last bar", "Freshness"]],
               "sectors": markets.group(df, "US sectors")[["Name", "1D %", "1W %", "1M %", "YTD %"]],
               "themes": markets.group(df, "US themes")[["Name", "1D %", "1W %", "1M %", "YTD %"]],
               "mag7": markets.group(df, "Magnificent 7")[["Name", "1D %", "1W %", "1M %", "YTD %"]],
               "yields_credit": pd.concat([markets.group(df, "US Treasury yields"), markets.group(df, "Credit & bonds")])[
                   ["Name", "Last", "1D chg", "1W %", "1M %", "Last bar"]],
               "fred_macro": mc.get("macro"), "recession_signals": mc.get("recession_signals"),
               "news": iu.ranked_news(2, "US").head(30)[["tier", "headline", "source", "published_utc", "url", "info_type", "topics"]],
               "not_available": [u[0] for u in UNAVAILABLE]}
    ui.gemini_panel("us_analyst", "Explain the US market environment",
                    lambda: gemini.intel_analysis("us_market_analyst", payload, "US"),
                    payload_for_links=payload)

ui.disclaimer()
