"""Earnings & Catalysts — Event Risk & Corporate Reporting Calendar."""
from __future__ import annotations

from datetime import date, timedelta
import pandas as pd
import streamlit as st

from tradingos import watchlist
from tradingos.ai import gemini
from tradingos.data.providers import get_market_provider
from tradingos.db.models import EconEvent
from tradingos.db.session import session_scope
from tradingos.journal.service import trades_dataframe
from tradingos.services import fundamentals, upcoming_events
from tradingos.ui import components as ui
from tradingos.ui.state import selected_ticker, valid_ticker

ui.render_top_bar(show_refresh=False)

st.markdown("## Earnings & Catalysts")
st.caption("Earnings release dates · Historical surprise track record · Macro economic calendar · Overnight gap risk management")

cfg = ui.settings()

tab_cal, tab_deep, tab_events = st.tabs(["Earnings Calendar", "Earnings Intelligence", "Economic Event Calendar"])

with tab_cal:
    wl = [w.ticker for w in watchlist.items()]
    ot = trades_dataframe("OPEN")
    op = list(ot["ticker"].unique()) if len(ot) else []

    tickers_s = st.text_input("Symbols to Monitor (Watchlist & Open Trades)", ",".join(dict.fromkeys(op + wl)))
    tickers = [t.strip().upper() for t in tickers_s.split(",") if t.strip() and valid_ticker(t)]

    if not tickers:
        ui.empty_state("No symbols specified. Add symbols to your Watchlist or enter tickers above.")
    else:
        rows = []
        prog = st.progress(0.0, "Checking earnings schedules...")
        for i, t in enumerate(tickers[:35]):
            r = get_market_provider().earnings(t)
            nd = (r.data or {}).get("next_date") if r.ok else None
            days = (nd - date.today()).days if nd else None
            gap_flag = (
                "⚠️ WITHIN 28D — OVERNIGHT GAP RISK"
                if days is not None and days <= 28
                else ("Confirmed" if nd else "Date pending IR announcement")
            )
            rows.append({
                "Ticker": t,
                "Next Earnings": nd,
                "Days Until": days,
                "Active Trade": "YES" if t in op else "—",
                "Risk Advisory": gap_flag,
            })
            prog.progress((i + 1) / min(len(tickers), 35))
        prog.empty()

        cal = pd.DataFrame(rows).sort_values("Days Until", na_position="last")
        st.dataframe(cal, hide_index=True, width="stretch")
        st.caption("Source: Yahoo Finance via provider layer. Verify against official corporate investor relations sites.")

with tab_deep:
    t = st.text_input("Analyze Symbol Earnings History", selected_ticker("AAPL")).strip().upper()
    if t and valid_ticker(t):
        with st.spinner(f"Loading earnings track record for {t}..."):
            f = fundamentals(t)
        for e in f["errors"]:
            st.warning(e)

        info = f["info"]
        st.markdown(f"### {info.get('longName', t)} · {info.get('industry', 'Equities')}")

        if f["next_earnings"]:
            dte = (f["next_earnings"] - date.today()).days
            if dte <= 28:
                st.markdown(
                    f'<div style="background:rgba(244,63,94,0.08);border:1px solid rgba(244,63,94,0.3);border-radius:4px;padding:8px 12px;margin-bottom:10px;">'
                    f'  <span style="color:#F43F5E;font-weight:700;">⚠️ GAP RISK WARNING:</span> '
                    f'  <span style="color:#F1F5F9;">Next earnings release in <strong>{dte} days</strong> ({f["next_earnings"]}). Holding a swing trade through earnings exposes capital to unmanaged overnight gap risk.</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        m = st.columns(6)
        def pc(k):
            v = info.get(k)
            return ui.pct(v * 100, 1, False) if isinstance(v, (int, float)) else "—"

        m[0].metric("Revenue Growth YoY", pc("revenueGrowth"))
        m[1].metric("Gross Margin", pc("grossMargins"))
        m[2].metric("Operating Margin", pc("operatingMargins"))
        m[3].metric("Forward P/E", ui.num(info.get("forwardPE"), 1))
        m[4].metric("Debt / Equity", ui.num(info.get("debtToEquity"), 1))
        m[5].metric("Free Cash Flow", ui.money(info.get("freeCashflow"), 0))

        if f["quarters"]:
            st.markdown("### Quarterly Statement Momentum")
            q = pd.DataFrame(f["quarters"])
            st.dataframe(q, hide_index=True, width="stretch")

        if f["earnings_history"]:
            st.markdown("### Consensus EPS Beats vs Actuals")
            st.dataframe(pd.DataFrame(f["earnings_history"]), hide_index=True, width="stretch")

        # Gemini Earnings Evaluation
        st.markdown("### AI Earnings & Fundamental Assessment")
        ui.gemini_panel(
            f"earnings_{t}",
            "Generate AI Earnings Assessment",
            lambda: gemini.earnings_analysis(t, {"ticker": t, "fundamentals": f}),
            help_text="Assesses quarterly revenue trajectory, margin expansion, and gap risk.",
        )

with tab_events:
    st.caption("Official US Macro Schedules: Federal Reserve FOMC · Bureau of Labor Statistics (CPI, Payrolls) · Bureau of Economic Analysis (GDP)")
    with st.expander("➕ Log Upcoming Economic Event", expanded=False):
        with st.form("add_event", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([1.2, 2.2, 1.2, 1.2])
            d = c1.date_input("Event Date", date.today() + timedelta(days=7))
            title = c2.text_input("Event Title (e.g. FOMC Rate Decision, US CPI)")
            catg = c3.selectbox("Category", ["fed", "inflation", "jobs", "gdp", "earnings", "geopolitical", "other"])
            imp = c4.selectbox("Importance", ["high", "medium", "low"])
            src = st.text_input("Official Source URL")
            if st.form_submit_button("Save Economic Event", type="primary") and title.strip():
                with session_scope() as s:
                    s.add(EconEvent(event_date=d, title=title.strip(), category=catg, importance=imp, source_url=src.strip()))
                st.toast("Economic event recorded.")
                st.rerun()

    ev_df = upcoming_events(days=35)
    if ev_df.empty:
        ui.empty_state("No upcoming macro events scheduled in the next 35 days.")
    else:
        st.dataframe(ev_df[["date", "event", "category", "importance", "source_url"]], hide_index=True, width="stretch")

ui.disclaimer()
