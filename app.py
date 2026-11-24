"""GLOBAL MARKET INTELLIGENCE — powered by AI Trading OS.

Run:  streamlit run app.py
"""
import logging
from datetime import datetime, timezone

import streamlit as st

from tradingos.data.base import NY
from tradingos.db.session import daily_backup_if_needed, longterm_engine, trading_engine
from tradingos.ui import components as ui
from tradingos.ui.state import select_ticker, valid_ticker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title="Global Market Intelligence — AI Trading OS",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.setup_page()

# Initialise both databases (separate files) and take one automatic backup per day.
trading_engine()
longterm_engine()
if "backup_checked" not in st.session_state:
    try:
        daily_backup_if_needed()
    except Exception as e:
        logging.getLogger(__name__).warning("Automatic backup failed: %s", e)
    st.session_state["backup_checked"] = True

# Navigation: intelligence first (Daily Briefing is the landing page), trading tools preserved below.
pages = {
    "Intelligence": [
        st.Page("views/daily_briefing.py", title="Daily Briefing", icon=":material/newspaper:", default=True),
        st.Page("views/global_markets.py", title="Global Markets", icon=":material/public:"),
        st.Page("views/us_markets.py", title="US Markets", icon=":material/flag:"),
        st.Page("views/india_markets.py", title="Indian Markets", icon=":material/currency_rupee:"),
        st.Page("views/gold_commodities.py", title="Gold & Commodities", icon=":material/diamond:"),
        st.Page("views/geopolitics.py", title="Geopolitics", icon=":material/travel_explore:"),
        st.Page("views/trends_radar.py", title="Trends Radar", icon=":material/radar:"),
        st.Page("views/economic_calendar.py", title="Economic Calendar", icon=":material/calendar_month:"),
        st.Page("views/news.py", title="News Intelligence", icon=":material/feed:"),
        st.Page("views/ai_analyst.py", title="AI Research", icon=":material/psychology:"),
    ],
    "Trading Tools": [
        st.Page("views/command_centre.py", title="Trading Desk", icon=":material/dashboard:"),
        st.Page("views/market_intel.py", title="US Regime & Macro", icon=":material/monitoring:"),
        st.Page("views/scanner.py", title="Stock Scanner", icon=":material/manage_search:"),
        st.Page("views/technical.py", title="Technical Analysis", icon=":material/candlestick_chart:"),
        st.Page("views/trade_planner.py", title="Trade Planner", icon=":material/ads_click:"),
        st.Page("views/watchlist.py", title="Watchlist", icon=":material/visibility:"),
        st.Page("views/earnings.py", title="Earnings & Catalysts", icon=":material/event:"),
        st.Page("views/journal.py", title="Trading Journal", icon=":material/menu_book:"),
        st.Page("views/performance.py", title="Performance Analytics", icon=":material/query_stats:"),
        st.Page("views/longterm.py", title="Long-Term Portfolio", icon=":material/account_balance:"),
    ],
    "System": [
        st.Page("views/system_health.py", title="System Health", icon=":material/health_and_safety:"),
        st.Page("views/settings_page.py", title="Settings", icon=":material/tune:"),
    ],
}

sess = ui.market_session_info()

with st.sidebar:
    st.markdown(
        f'<div style="padding: 10px 4px 14px 4px; border-bottom: 1px solid #162030; margin-bottom: 12px;">'
        f'  <div style="display:flex;align-items:center;justify-content:space-between;">'
        f'    <span style="font-weight:700;font-size:0.9rem;letter-spacing:0.06em;color:#F1F5F9;">GLOBAL MARKET INTELLIGENCE</span>'
        f'    <span class="{sess["badge_cls"]}" style="font-size:0.65rem;padding:1px 6px;">{sess["status"]}</span>'
        f'  </div>'
        f'  <div style="font-size:0.72rem;color:#64748B;margin-top:3px;">powered by AI Trading OS · US · India · Gold · Macro</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Global Quick Search
    quick_t = st.text_input(
        "Quick Ticker Jump",
        placeholder="e.g. NVDA, AAPL, MSFT",
        label_visibility="collapsed",
        key="_nav_quick_ticker",
    ).strip().upper()
    if quick_t and valid_ticker(quick_t):
        if quick_t != st.session_state.get("active_ticker"):
            select_ticker(quick_t)
            st.toast(f"Active ticker set to {quick_t}")

pg = st.navigation(pages)
pg.run()
