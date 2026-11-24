"""Global Market Intelligence — daily briefing and research terminal.

Run:  streamlit run app.py
"""
import logging
import sys
from pathlib import Path

# Ensure repository root is on sys.path for Streamlit Cloud deployment
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Reload tradingos modules on hot-reload to prevent stale classes in long-running processes
for mod in list(sys.modules):
    if mod == "tradingos" or mod.startswith("tradingos."):
        del sys.modules[mod]

import streamlit as st

from tradingos.db.session import daily_backup_if_needed, trading_engine
from tradingos.ui import components as ui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title="Global Market Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",   # expanded on desktop, collapsed behind the menu button on phones
)
ui.setup_page()

trading_engine()   # create/migrate tables
if "backup_checked" not in st.session_state:
    try:
        daily_backup_if_needed()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("Automatic backup failed: %s", e)
    st.session_state["backup_checked"] = True

P = {
    "briefing": st.Page("views/daily_briefing.py", title="Daily Briefing", icon=":material/newspaper:", default=True),
    "global": st.Page("views/global_markets.py", title="Global Markets", icon=":material/public:"),
    "us": st.Page("views/us_markets.py", title="US Markets", icon=":material/flag:"),
    "india": st.Page("views/india_markets.py", title="Indian Markets", icon=":material/currency_rupee:"),
    "gold": st.Page("views/gold_commodities.py", title="Gold & Commodities", icon=":material/diamond:"),
    "geo": st.Page("views/geopolitics.py", title="Geopolitics", icon=":material/travel_explore:"),
    "x": st.Page("views/x_intelligence.py", title="X Intelligence", icon=":material/forum:"),
    "live": st.Page("views/live_newsroom.py", title="Live Newsroom", icon=":material/live_tv:"),
    "trends": st.Page("views/trends_radar.py", title="Global Trends Radar", icon=":material/radar:"),
    "calendar": st.Page("views/economic_calendar.py", title="Economic Calendar", icon=":material/calendar_month:"),
    "archive": st.Page("views/news_archive.py", title="News Archive", icon=":material/inventory_2:"),
    "chat": st.Page("views/ai_research.py", title="AI Research Chat", icon=":material/psychology:"),
    "settings": st.Page("views/settings_page.py", title="Settings", icon=":material/tune:"),
    "health": st.Page("views/system_health.py", title="System Health", icon=":material/health_and_safety:"),
}
pages = {
    "": [P["briefing"]],
    "Markets": [P["global"], P["us"], P["india"], P["gold"]],
    "Intelligence": [P["geo"], P["x"], P["live"], P["trends"], P["calendar"], P["archive"]],
    "Research": [P["chat"]],
    "System": [P["settings"], P["health"]],
}

with st.sidebar:
    st.markdown(
        '<div style="padding:2px 6px 10px;border-bottom:1px solid var(--border);margin-bottom:6px;">'
        '<div style="font-weight:700;font-size:0.82rem;letter-spacing:0.08em;color:var(--text-strong);">'
        'GLOBAL MARKET INTELLIGENCE</div>'
        '<div style="font-size:0.72rem;color:var(--faint);margin-top:2px;">US · India · Gold · Geopolitics · Macro</div>'
        '</div>',
        unsafe_allow_html=True,
    )

pg = st.navigation(pages, expanded=True)

# Phone navigation: fixed bottom bar with the five most-used pages (hidden ≥768px by CSS). Every other page is in the
# menu (top-left button). Hidden on the chat page, whose message box occupies the bottom of the screen.
if pg.url_path != "ai_research":
    with st.container(horizontal=True, key="mnav", gap=None):
        for k, label in (("briefing", "Briefing"), ("global", "Markets"), ("archive", "News"),
                         ("calendar", "Calendar"), ("chat", "AI Chat")):
            st.page_link(P[k], label=label, icon=P[k].icon)

pg.run()
