"""Watchlist — Intelligent Portfolio Monitoring & Price Alerts."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos import watchlist
from tradingos.ai import gemini
from tradingos.ui import components as ui
from tradingos.ui.state import select_ticker, valid_ticker

ui.render_top_bar(show_refresh=False)
ui.show_flash()

st.markdown("## Watchlist & Setup Monitoring")
st.caption("Active tracking for candidate equities · Price & technical alerts · AI setup prioritization")

with st.expander("➕ Add Symbol to Watchlist", expanded=False):
    with st.form("wl_add", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns([1.2, 2.2, 1.2, 1.0, 1.0])
        t = c1.text_input("Symbol", placeholder="e.g. AMD")
        notes = c2.text_input("Thesis / Entry Trigger", placeholder="e.g. Waiting for 50DMA bounce")
        tags = c3.text_input("Tags", placeholder="e.g. Semis, Breakout")
        above = c4.number_input("Alert Above ($)", 0.0, value=0.0, step=0.5)
        below = c5.number_input("Alert Below ($)", 0.0, value=0.0, step=0.5)
        if st.form_submit_button("Save Symbol to Watchlist", type="primary"):
            if not valid_ticker(t):
                st.error("Please provide a valid ticker symbol.")
            else:
                watchlist.add(t, notes, tags, above or None, below or None)
                st.toast(f"{t.upper()} added to Watchlist.")
                st.rerun()

# Active alert notices
alerts = watchlist.open_alerts()
if alerts:
    st.markdown("### Active Price Alerts")
    for a in alerts:
        a1, a2 = st.columns([5, 1])
        with a1:
            st.markdown(
                f'<div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);border-radius:4px;padding:8px 12px;margin-bottom:6px;">'
                f'  <span style="color:#F59E0B;font-weight:600;font-size:0.75rem;">🔔 ALERT TRIGGERED</span> '
                f'  <span style="color:#F1F5F9;font-size:0.84rem;">{a.message}</span> '
                f'  <span style="color:#64748B;font-size:0.72rem;">({a.created_at:%Y-%m-%d %H:%M} UTC)</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with a2:
            if st.button("Acknowledge", key=f"ack{a.id}", width="stretch"):
                watchlist.acknowledge(a.id)
                st.rerun()

with st.spinner("Pricing watchlist equities..."):
    snap = watchlist.watchlist_snapshot()

if snap.empty:
    ui.empty_state("Your watchlist is currently empty. Add candidate symbols above or from the Stock Scanner.")
    st.stop()

# Watchlist Table
st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
st.dataframe(
    ui.color_pct_cols(snap, ["1D %", "1M %"]),
    hide_index=True,
    width="stretch",
    column_config={
        "Last": st.column_config.NumberColumn("Price", format="$%.2f"),
        "1D %": st.column_config.NumberColumn("1D %", format="%+.2f%%"),
        "1M %": st.column_config.NumberColumn("1M %", format="%+.2f%%"),
    },
)
st.caption("Prices reflect latest available market close from provider. Alerts compare against current close.")

# Check Alerts Trigger
if st.button("🔔 Check Alerts Against Latest Prices"):
    new = watchlist.check_alerts()
    if new:
        ui.flash(f"{len(new)} alert(s) triggered.", "warning")
        st.rerun()
    st.success("Alert check complete — no new trigger events.")

# Quick Action Drawer
st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
st.markdown("### Symbol Actions")
if not snap.empty:
    col_sym, col_act1, col_act2, col_act3 = st.columns([1.5, 1.2, 1.2, 1.0])
    with col_sym:
        pick = st.selectbox("Select Watchlist Symbol", list(snap["Ticker"]), key="_wl_action_pick")
    with col_act1:
        if st.button("📊 Technical Analysis", width="stretch"):
            select_ticker(pick)
            st.switch_page("views/technical.py")
    with col_act2:
        if st.button("🎯 Plan Trade", width="stretch"):
            select_ticker(pick)
            st.switch_page("views/trade_planner.py")
    with col_act3:
        if st.button("🗑 Remove", width="stretch"):
            watchlist.remove(pick)
            st.toast(f"{pick} removed from Watchlist.")
            st.rerun()

# AI Watchlist Synthesis
st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
st.markdown("### AI Watchlist Prioritization & Review")

def _review_watchlist():
    payload = {
        "watchlist": snap.to_dict(orient="records"),
        "count": len(snap),
    }
    return gemini.get_client().generate(
        f"Review this trader's current watchlist candidates. Identify which 2-3 symbols deserve immediate attention "
        f"and rank them based on trend, relative strength, and setup quality. Highlight any immediate risks.\n\n"
        f"DATA:\n{payload}",
        system="You are a senior hedge-fund swing-trading mentor. Be direct, concise, and risk-focused.",
    )

ui.gemini_panel(
    "watchlist_review",
    "Generate AI Watchlist Review",
    _review_watchlist,
    help_text="Evaluates your watchlist and highlights which setups are closest to actionable execution.",
)

ui.disclaimer()
