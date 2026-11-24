from dataclasses import asdict, fields

import streamlit as st

from tradingos.ai.gemini import test_connection, test_gemini_connection, test_groq_connection
from tradingos.config import load_config
from tradingos.data import cache
from tradingos.settings import TradingSettings, load_settings, save_settings
from tradingos.ui import components as ui

ui.render_top_bar(show_refresh=False)

st.markdown("## System Settings & Platform Health")
st.caption("API provider integrations · Risk engine defaults · Push notifications · Database maintenance")

cfg = load_settings()
app = load_config()

st.markdown("### External API Integrations & Health")
c0, c1, c2, c3, c4 = st.columns(5)
with c0:
    st.markdown(
        f'<div class="term-card">'
        f'  <div class="term-card-header">'
        f'    <span class="term-label">Groq AI (LPU)</span>'
        f'    {ui.badge("ACTIVE" if app.groq_configured else "DISABLED", "green" if app.groq_configured else "neutral")}'
        f'  </div>'
        f'  <div style="font-size:0.75rem;color:#94A3B8;margin-bottom:8px;">Model: <code>{app.groq_model}</code><br/>Ultra-fast reasoning</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.button("Test Groq", disabled=not app.groq_configured, width="stretch"):
        ok, msg = test_groq_connection()
        (st.success if ok else st.error)(msg)
with c1:
    st.markdown(
        f'<div class="term-card">'
        f'  <div class="term-card-header">'
        f'    <span class="term-label">Google Gemini</span>'
        f'    {ui.badge("ACTIVE" if app.gemini_configured else "DISABLED", "green" if app.gemini_configured else "neutral")}'
        f'  </div>'
        f'  <div style="font-size:0.75rem;color:#94A3B8;margin-bottom:8px;">Model: <code>{app.gemini_model}</code><br/>Auto-fallback chain</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.button("Test Gemini", disabled=not app.gemini_configured, width="stretch"):
        ok, msg = test_gemini_connection()
        (st.success if ok else st.error)(msg)
with c2:
    st.markdown(
        f'<div class="term-card">'
        f'  <div class="term-card-header">'
        f'    <span class="term-label">Finnhub Market</span>'
        f'    {ui.badge("ACTIVE" if app.finnhub_configured else "DISABLED", "green" if app.finnhub_configured else "neutral")}'
        f'  </div>'
        f'  <div style="font-size:0.75rem;color:#94A3B8;margin-bottom:8px;">Real-time quotes, news & earnings</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.button("Test Finnhub", disabled=not app.finnhub_configured, width="stretch"):
        from tradingos.data.providers import test_finnhub_connection
        ok, msg = test_finnhub_connection()
        (st.success if ok else st.error)(msg)
with c3:
    st.markdown(
        f'<div class="term-card">'
        f'  <div class="term-card-header">'
        f'    <span class="term-label">FMP Financials</span>'
        f'    {ui.badge("ACTIVE" if app.fmp_configured else "DISABLED", "green" if app.fmp_configured else "neutral")}'
        f'  </div>'
        f'  <div style="font-size:0.75rem;color:#94A3B8;margin-bottom:8px;">Statements, balance sheets & ratios</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.button("Test FMP", disabled=not app.fmp_configured, width="stretch"):
        from tradingos.data.providers import test_fmp_connection
        ok, msg = test_fmp_connection()
        (st.success if ok else st.error)(msg)
with c4:
    st.markdown(
        f'<div class="term-card">'
        f'  <div class="term-card-header">'
        f'    <span class="term-label">St. Louis Fed (FRED)</span>'
        f'    {ui.badge("ACTIVE" if app.fred_api_key else "CSV FALLBACK", "green" if app.fred_api_key else "amber")}'
        f'  </div>'
        f'  <div style="font-size:0.75rem;color:#94A3B8;margin-bottom:8px;">17 macro series & yield observations</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.button("Test FRED", disabled=not app.fred_api_key, width="stretch"):
        from tradingos.data.providers import test_fred_connection
        ok, msg = test_fred_connection()
        (st.success if ok else st.error)(msg)

c_m1, c_m2 = st.columns([3, 1])
with c_m1:
    st.caption(f"Secrets live only in `.env` (git-ignored). SEC EDGAR: {'✅ Active' if app.sec_user_agent else '⚪ Disabled'}. "
               f"Data directory: `{app.data_dir}`")
with c_m2:
    if st.button("Clear data cache"):
        st.success(f"Removed {cache.clear()} cached files.")
        st.cache_data.clear()

st.divider()
st.subheader("Capital & risk")
st.caption("Defaults: $300 capital, 1% risk/trade, 2% max open risk, 3 positions. Changes apply to new plans only.")
with st.form("settings"):
    c1, c2, c3, c4 = st.columns(4)
    cap = c1.number_input("Starting trading capital (USD)", 1.0, value=float(cfg.starting_capital_usd), step=50.0)
    rpt = c2.number_input("Risk per trade %", 0.1, 5.0, float(cfg.risk_per_trade_pct), 0.1)
    mor = c3.number_input("Max aggregate open risk %", 0.1, 10.0, float(cfg.max_open_risk_pct), 0.1)
    mp = c4.number_input("Max simultaneous positions", 1, 10, int(cfg.max_positions))
    c1, c2, c3, c4 = st.columns(4)
    inc = c1.selectbox("Share increment", [1.0, 0.1, 0.01, 0.001, 0.0001],
                       index=[1.0, 0.1, 0.01, 0.001, 0.0001].index(cfg.share_increment)
                       if cfg.share_increment in [1.0, 0.1, 0.01, 0.001, 0.0001] else 0,
                       help="1 = whole shares only. Choose a fractional increment only if your broker supports "
                            "fractional orders for that stock.")
    mrr = c2.number_input("Min reward:risk for 'Plan eligible'", 1.0, 10.0, float(cfg.min_reward_risk), 0.1)
    mtm = c3.number_input("Overtrading flag (entries/month)", 1, 50, int(cfg.max_trades_per_month))
    mss = c4.number_input("Min sample before conclusions", 5, 200, int(cfg.min_sample_for_conclusions))

    st.markdown("**Costs (estimates — verify against Vested's current pricing page and your bank)**")
    c1, c2, c3, c4 = st.columns(4)
    cpo = c1.number_input("Commission per order $", 0.0, value=float(cfg.commission_per_order_usd), step=0.1)
    cpc = c2.number_input("Commission % of order", 0.0, value=float(cfg.commission_pct), step=0.05)
    cmn = c3.number_input("Minimum commission $", 0.0, value=float(cfg.commission_min_usd), step=0.1)
    spr = c4.number_input("Spread bps per side", 0.0, value=float(cfg.spread_bps), step=1.0)
    c1, c2, c3, c4 = st.columns(4)
    slp = c1.number_input("Slippage bps per side", 0.0, value=float(cfg.slippage_bps), step=1.0)
    fxm = c2.number_input("FX markup % (INR↔USD)", 0.0, value=float(cfg.fx_markup_pct), step=0.1)
    fxi = c3.checkbox("Include FX in each trade's cost estimate", cfg.include_fx_in_trade_costs)
    tax = c4.number_input("Est. tax rate on short-term gains %", 0.0, 60.0, float(cfg.est_tax_rate_pct), 1.0,
                          help="Estimate only. For Indian residents, short-term gains on US stocks are generally taxed "
                               "at slab rates; consult a tax professional.")

    st.markdown("**Scanner defaults**")
    c1, c2, c3, c4 = st.columns(4)
    mpx = c1.number_input("Min price", 1.0, value=float(cfg.min_price))
    mdv = c2.number_input("Min avg $ volume (M)", 1.0, value=float(cfg.min_avg_dollar_volume_m))
    rmin = c3.number_input("RSI min", 0.0, 100.0, float(cfg.rsi_min))
    rmax = c4.number_input("RSI max", 0.0, 100.0, float(cfg.rsi_max))
    c1, c2, c3, c4 = st.columns(4)
    rvb = c1.number_input("Breakout rel. volume", 1.0, 10.0, float(cfg.rel_volume_breakout), 0.1)
    rvu = c2.number_input("Unusual rel. volume", 1.0, 10.0, float(cfg.rel_volume_unusual), 0.1)
    ewd = c3.number_input("Earnings warning days", 1, 60, int(cfg.earnings_warning_days))
    r200 = c4.checkbox("Require above 200DMA", cfg.require_above_200dma)
    extra = st.text_input("Extra tickers to scan (comma separated)", ",".join(cfg.extra_tickers))
    nmax = st.number_input("Drop news older than (days)", 1, 60, int(cfg.news_max_age_days))

    st.markdown("**Push & Webhook Alert Notifications**")
    st.caption("Receive instant alerts when stop/target is hit or watchlist price triggers fire.")
    a1, a2 = st.columns(2)
    ntfy = a1.text_input("ntfy.sh topic name (free instant push to phone/browser)", value=cfg.alert_ntfy_topic or "",
                         help="e.g. 'swinger_alerts_mycode'. Install ntfy on Android/iOS or visit ntfy.sh/your-topic")
    webhook = a2.text_input("Discord / Slack / Generic Webhook URL", value=cfg.alert_webhook_url or "")
    a3, a4 = st.columns(2)
    tg_token = a3.text_input("Telegram Bot Token (optional)", value=cfg.alert_telegram_bot_token or "", type="password")
    tg_chat = a4.text_input("Telegram Chat ID (optional)", value=cfg.alert_telegram_chat_id or "")

    if st.form_submit_button("Save settings", type="primary"):
        new = TradingSettings(**{**asdict(cfg), **dict(
            starting_capital_usd=cap, risk_per_trade_pct=rpt, max_open_risk_pct=mor, max_positions=int(mp),
            share_increment=float(inc), min_reward_risk=mrr, max_trades_per_month=int(mtm),
            min_sample_for_conclusions=int(mss), commission_per_order_usd=cpo, commission_pct=cpc,
            commission_min_usd=cmn, spread_bps=spr, slippage_bps=slp, fx_markup_pct=fxm, include_fx_in_trade_costs=fxi,
            est_tax_rate_pct=tax, min_price=mpx, min_avg_dollar_volume_m=mdv, rsi_min=rmin, rsi_max=rmax,
            rel_volume_breakout=rvb, rel_volume_unusual=rvu, earnings_warning_days=int(ewd),
            require_above_200dma=r200, news_max_age_days=int(nmax),
            extra_tickers=[t.strip().upper() for t in extra.split(",") if t.strip()],
            alert_ntfy_topic=ntfy.strip(), alert_webhook_url=webhook.strip(),
            alert_telegram_bot_token=tg_token.strip(), alert_telegram_chat_id=tg_chat.strip())})
        try:
            save_settings(new)
            st.success("Saved.")
            st.cache_data.clear()
        except ValueError as e:
            st.error(str(e))

if st.button("🔔 Send test alert ping"):
    from tradingos.alerts import test_notification
    res = test_notification(cfg)
    for k, v in res.items():
        st.write(f"**{k.upper()}:** {v}")

with st.expander("Current settings (raw)"):
    st.json({f.name: getattr(cfg, f.name) for f in fields(cfg)})
risk_budget = cfg.starting_capital_usd * cfg.risk_per_trade_pct / 100
st.caption(f"At these settings a full-risk trade may lose about {ui.money(risk_budget)}. With whole shares, any stock whose "
           f"stop is more than {ui.money(risk_budget)} below entry cannot be traded within the limit; the planner "
           "will mark it unsuitable rather than raise risk.")
