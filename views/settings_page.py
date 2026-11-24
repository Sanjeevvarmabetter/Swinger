"""Settings — data/AI provider status and connection tests, research parameters, maintenance."""
from dataclasses import asdict

import streamlit as st

from tradingos.ai.gemini import FALLBACK_MODELS, quota_status, test_gemini_connection, test_groq_connection
from tradingos.config import load_config
from tradingos.data import cache
from tradingos.db.session import backup_databases, restore_note
from tradingos.intel import xintel
from tradingos.settings import AppSettings, load_settings, save_settings
from tradingos.ui import components as ui

ui.render_top_bar(show_refresh=False)
ui.page_header("Settings", "Provider connections, research parameters and maintenance. API keys are read only from "
                           ".env or Streamlit secrets — they are never shown or stored by this page.")

cfg = load_settings()
app = load_config()


def _provider(title: str, active: bool, detail: str, state_label: str | None = None, test=None, key: str = "") -> None:
    with st.container(border=True):
        badge = ui.badge(state_label or ("Configured" if active else "Not configured"),
                         "green" if active else ("amber" if state_label else "neutral"))
        st.markdown(f'<div class="term-card-header"><span class="term-label">{title}</span>{badge}</div>'
                    f'<div class="tos-muted" style="margin:4px 0 6px">{detail}</div>', unsafe_allow_html=True)
        if test is not None:
            if st.button("Test connection", key=f"test_{key}", disabled=not active, width="stretch"):
                with st.spinner("Testing…"):
                    ok, msg = test()
                (st.success if ok else st.error)(msg)


st.markdown('<div class="sec-title">AI providers</div>', unsafe_allow_html=True)
a1, a2 = st.columns(2)
with a1:
    _provider("Groq (primary)", app.groq_configured, f"Model {app.groq_model} · streaming chat, briefings",
              test=test_groq_connection, key="groq")
with a2:
    qs = quota_status()
    detail = f"Model {app.gemini_model} · fallback chain of {len(FALLBACK_MODELS)} models"
    if qs:
        detail += " · out of quota: " + ", ".join(f"{q['model']} ({q['resets_in_hours']}h)" for q in qs)
    _provider("Google Gemini", app.gemini_configured, detail, test=test_gemini_connection, key="gemini")
st.caption("With both keys set, Groq answers first and Gemini is used automatically if Groq fails "
           "(AI_PROVIDER=auto). Set AI_PROVIDER=gemini or groq in .env to force one.")

st.markdown('<div class="sec-title">Data providers</div>', unsafe_allow_html=True)
d1, d2, d3, d4 = st.columns(4)
with d1:
    from tradingos.data.providers import test_finnhub_connection
    _provider("Finnhub", app.finnhub_configured, "News, earnings & IPO calendars", test=test_finnhub_connection,
              key="finnhub")
with d2:
    from tradingos.data.providers import test_fmp_connection
    _provider("FMP", app.fmp_configured, "Company fundamentals", test=test_fmp_connection, key="fmp")
with d3:
    from tradingos.data.providers import test_fred_connection
    _provider("FRED (St. Louis Fed)", app.fred_configured, "Macro series & release calendar",
              state_label=None if app.fred_configured else "Public CSV fallback", test=test_fred_connection, key="fred")
with d4:
    _provider("X API", xintel.configured(), f"X Intelligence · budget {xintel.daily_limit()} requests/day",
              key="x")
st.caption(f"Yahoo Finance (delayed prices) needs no key. SEC EDGAR filings: "
           f"{'enabled' if app.sec_user_agent else 'disabled (set SEC_USER_AGENT)'}. Live checks of every endpoint "
           "are on the System Health page.")

st.markdown('<div class="sec-title">Research parameters</div>', unsafe_allow_html=True)
with st.form("settings"):
    c1, c2, c3 = st.columns(3)
    bl = c1.number_input("Breakout lookback (days)", 5, 260, int(cfg.breakout_lookback),
                         help="Used in company snapshots supplied to the AI Research Chat.")
    rs = c2.number_input("Relative-strength lookback (days)", 5, 260, int(cfg.rs_lookback_days))
    rv = c3.number_input("High relative-volume threshold (×)", 0.5, 10.0, float(cfg.rel_volume_breakout), 0.1)
    c4, c5 = st.columns([1, 2])
    nmax = c4.number_input("Drop news older than (days) on refresh", 1, 60, int(cfg.news_max_age_days))
    extra = c5.text_input("Extra US tickers for the breadth universe (comma-separated)", ",".join(cfg.extra_tickers))
    if st.form_submit_button("Save settings", type="primary"):
        new = AppSettings(**{**asdict(cfg), **dict(
            breakout_lookback=int(bl), rs_lookback_days=int(rs), rel_volume_breakout=float(rv),
            news_max_age_days=int(nmax), extra_tickers=[t.strip().upper() for t in extra.split(",") if t.strip()])})
        try:
            save_settings(new)
            st.cache_data.clear()
            st.success("Saved.")
        except ValueError as e:
            st.error(str(e))

st.markdown('<div class="sec-title">Maintenance</div>', unsafe_allow_html=True)
with st.container(horizontal=True, gap="small"):
    if st.button("Clear data cache", icon=":material/delete_sweep:",
                 help="Forces fresh downloads of market data, calendars and feeds."):
        n = cache.clear()
        st.cache_data.clear()
        st.toast(f"Removed {n} cached files.")
    if st.button("Back up database now", icon=":material/backup:"):
        made = backup_databases()
        st.toast(f"Backup written: {made[0].name}" if made else "Nothing to back up yet.")
st.caption(f"Data directory: `{app.data_dir}` · {restore_note()} One automatic backup is made per day.")

ui.disclaimer()
