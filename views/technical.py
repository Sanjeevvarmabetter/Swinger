"""Technical Analysis — TradingView-Inspired Chart Workstation."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.analysis import indicators as ind
from tradingos.analysis.technical import explain
from tradingos.ui import charts, components as ui
from tradingos.ui.state import select_ticker, selected_ticker, stock_ctx, valid_ticker

ui.render_top_bar(show_refresh=False)

# Control Bar
c1, c2, c3, c4 = st.columns([1.5, 1.2, 1.5, 1.0])
ticker = c1.text_input("Symbol", selected_ticker("SPY")).strip().upper()
tf = c2.selectbox("Timeframe", ["Daily", "Weekly"], index=0)
mas = c3.multiselect("Moving Averages", [20, 50, 100, 200], default=[20, 50, 200])
show_bb = c4.checkbox("Bollinger Bands", value=True)

if not valid_ticker(ticker):
    st.error("Please enter a valid US equity or ETF ticker symbol.")
    st.stop()
select_ticker(ticker)

with st.spinner(f"Loading market data & technical indicators for {ticker}..."):
    ctx = stock_ctx(ticker)

if "error" in ctx:
    st.error(ctx["error"])
    ui.freshness_badge(ctx.get("data_meta"), "Prices")
    st.stop()

snap = ctx["daily"] if tf == "Daily" else ctx["weekly"]
df = ctx["df"] if tf == "Daily" else ind.to_weekly(ctx["df"])

if "error" in snap:
    st.warning(snap["error"])
    st.stop()

# Header Card
st.markdown(
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
    f'  <div>'
    f'    <span style="font-size:1.35rem;font-weight:700;color:#F8FAFC;">{ticker}</span> '
    f'    <span style="font-size:0.92rem;color:#94A3B8;">{ctx["name"]}</span> '
    f'    {ui.badge(ctx["sector"] or "ETF", "blue")}'
    f'  </div>'
    f'</div>',
    unsafe_allow_html=True,
)
ui.freshness_badge(ctx["data_meta"], "Prices")

# Metrics Banner
m = st.columns(7)
m[0].metric("Last Price", ui.num(snap["close"]), ui.pct(snap["change_1d_pct"], 2) + (" 1D" if tf == "Daily" else " 1W"))
m[1].metric("RSI (14)", ui.num(snap["rsi14"], 1))
m[2].metric("ATR (14)", ui.num(snap["atr14"]), ui.pct(snap["atr_pct"], 1, False) + " of px", delta_color="off")
m[3].metric("Relative Vol", ui.num(snap["rel_volume"]) + "×")
m[4].metric("RS vs SPY", ui.pct(snap["rs_vs_spy_pp"]).replace("%", "pp"))
m[5].metric("From 52W High", ui.pct(snap["pct_from_52w_high"]))
m[6].metric("Days to Earnings", ctx.get("days_to_earnings") if ctx.get("days_to_earnings") is not None else "n/a")

# Chart Controls
bars = st.slider("Lookback Bars", 60, 500 if tf == "Daily" else 260, 180 if tf == "Daily" else 104, label_visibility="collapsed")

# Main Price & Indicators Chart
st.plotly_chart(
    charts.price_chart(
        df,
        snap,
        mas=tuple(mas),
        bars=bars,
        show_bb=show_bb,
        ma_label="DMA" if tf == "Daily" else "WMA",
        title=f"{ticker} · {tf} Terminal Chart · Volume, RSI & MACD",
    ),
    width="stretch",
)

# Relative Strength Chart
if tf == "Daily":
    from tradingos.data.providers import get_market_provider
    spy = get_market_provider().history(["SPY"], period="2y")
    if spy.ok and "SPY" in spy.data:
        st.plotly_chart(charts.rs_chart(ctx["df"]["Close"], spy.data["SPY"]["Close"]), width="stretch")

st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)

# Technical Summary Panel
left, right = st.columns([1.3, 1])
with left:
    st.markdown("### Technical Summary & Support/Resistance")
    
    exp = explain(snap)
    summary_items = [
        ("Current Trend", exp.get("1. Trend", "")),
        ("Support Levels", exp.get("2. Support", "")),
        ("Resistance Levels", exp.get("3. Resistance", "")),
        ("Momentum", exp.get("4. Momentum", "")),
        ("Volume Profile", exp.get("5. Volume", "")),
        ("Potential Entry Zones", exp.get("6. Possible entry zones", "")),
        ("Invalidation Level", exp.get("7. Invalidation", "")),
    ]

    for label, val in summary_items:
        st.markdown(
            f'<div class="term-card" style="margin-bottom:6px;padding:8px 12px;">'
            f'  <div class="term-label" style="margin-bottom:3px;">{label}</div>'
            f'  <div style="font-size:0.84rem;color:#E2E8F0;line-height:1.4;">{val}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if snap.get("setups"):
        st.markdown(
            f'<div style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.3);border-radius:4px;padding:8px 12px;margin-top:8px;">'
            f'  <span style="font-size:0.80rem;font-weight:600;color:#10B981;">DETECTED SETUP:</span> '
            f'  <span style="font-size:0.84rem;color:#F1F5F9;">{"; ".join(snap["setups"])}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    if snap.get("overextended"):
        st.markdown(
            f'<div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);border-radius:4px;padding:8px 12px;margin-top:8px;">'
            f'  <span style="font-size:0.80rem;font-weight:600;color:#F59E0B;">OVEREXTENDED:</span> '
            f'  <span style="font-size:0.84rem;color:#F1F5F9;">Price is >2.5 ATR above 20DMA or RSI > 75. Chasing here creates unfavorable R:R.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

with right:
    st.markdown("### Multi-Timeframe Alignment")
    d, w = ctx["daily"], ctx["weekly"]
    
    align_df = pd.DataFrame(
        {
            "Daily": [d.get("trend"), d.get("structure"), ui.num(d.get("rsi14"), 1), "Bullish" if d.get("macd_bullish") else "Bearish"],
            "Weekly": [w.get("trend", w.get("error")), w.get("structure", ""), ui.num(w.get("rsi14"), 1), "Bullish" if w.get("macd_bullish") else "Bearish"],
        },
        index=["Trend", "Structure", "RSI (14)", "MACD Momentum"],
    )
    st.dataframe(align_df, width="stretch")
    st.caption("Supports and resistances are clustered swing pivots from displayed bars (±0.5 ATR / 1.5%). No subjective lines.")

    # Action buttons
    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("🎯 Plan Trade", width="stretch"):
            st.switch_page("views/trade_planner.py")
    with b2:
        if st.button("✨ AI Research", width="stretch"):
            st.switch_page("views/ai_analyst.py")
    with b3:
        if st.button("👁️ Add Watchlist", width="stretch"):
            from tradingos import watchlist
            watchlist.add(ticker, notes=f"From Technical: {snap.get('trend', '')}")
            st.toast(f"{ticker} added to Watchlist.")

st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
st.markdown("### AI Technical Interpretation")

payload = {
    "ticker": ticker,
    "timeframe_primary": tf,
    "daily": ctx["daily"],
    "weekly": ctx["weekly"],
    "data_meta": ctx["data_meta"],
    "sector_etf": ctx.get("sector_etf"),
    "days_to_earnings": ctx.get("days_to_earnings"),
}

ui.gemini_panel(
    f"ta_{ticker}",
    "Generate AI Technical Interpretation",
    lambda: gemini.technical_analysis(ticker, payload),
    help_text="Evaluates trend, support/resistance invalidation, volume confirmation, and bullish/bearish scenarios.",
)

ui.disclaimer()
