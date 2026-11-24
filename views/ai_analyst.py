"""AI Research — Institutional AI Analyst Workspace."""
from __future__ import annotations

import json
import streamlit as st

from tradingos.ai import gemini
from tradingos.config import load_config
from tradingos.journal.service import account_state, sizing_equity
from tradingos.services import ai_payload_from_context
from tradingos.ui import components as ui
from tradingos.ui.state import market_ctx, select_ticker, selected_ticker, stock_ctx, valid_ticker

ui.render_top_bar(show_refresh=False)

cfg_app = load_config()

st.markdown("## AI Research Workstation")
st.caption(
    "Institutional research assistant powered by Groq & Google Gemini · "
    "Python deterministically calculates all prices, ratios, and risk metrics; "
    "AI models interpret the structured evidence."
)

ai_ready = getattr(cfg_app, "ai_configured", getattr(cfg_app, "gemini_configured", False))
if not ai_ready:
    st.warning("AI is not configured. Add GROQ_API_KEY (recommended, free) or GEMINI_API_KEY to your .env file or Streamlit secrets.")

cfg = ui.settings()

# Top ticker input
col_t, col_info = st.columns([1.5, 3.5])
with col_t:
    t = st.text_input("Enter US Equity / ETF Symbol", selected_ticker("NVDA")).strip().upper()

tab_research, tab_chat, tab_portfolio, tab_audit = st.tabs(
    ["Institutional Research", "Analyst Chat", "Portfolio Risk Review", "Report Audit Log"]
)

if t and valid_ticker(t):
    select_ticker(t)
    with st.spinner(f"Aggregating verified financial data & metrics for {t}..."):
        ctx = stock_ctx(t)
else:
    ctx = {"error": "Enter a valid ticker symbol."}

with tab_research:
    if "error" in ctx:
        ui.empty_state(ctx["error"])
    else:
        # Header banner
        fund = ctx.get("fundamentals", {})
        info = fund.get("info", {}) if isinstance(fund, dict) else {}
        mcap_val = ui.money(info.get("market_cap")) if info.get("market_cap") else ""
        mcap_badge = ui.badge(f"Market Cap: {mcap_val}", "purple") if mcap_val else ""
        sec_badge = ui.badge(ctx["sector"] or "Equities", "blue")

        st.markdown(
            f'<div class="term-card" style="margin-bottom:12px;">'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
            f'    <div>'
            f'      <span style="font-size:1.30rem;font-weight:700;color:#F8FAFC;">{t} — {ctx["name"]}</span> '
            f'      {sec_badge} {mcap_badge}'
            f'    </div>'
            f'    <div style="display:flex;gap:6px;">'
            f'      {ui.badge("DATA: VERIFIED", "green")}'
            f'      {ui.badge("CALCULATIONS: PYTHON", "blue")}'
            f'      {ui.badge("INTERPRETATION: GEMINI", "amber")}'
            f'    </div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        ui.freshness_badge(ctx["data_meta"], "Market Data")

        # Business Model & Overview
        summary = info.get("business_summary") or info.get("description", "")
        if summary:
            with st.expander("Business Model & Corporate Profile", expanded=False):
                st.markdown(f"<div style='font-size:0.85rem;color:#CBD5E1;line-height:1.6;'>{summary}</div>", unsafe_allow_html=True)

        # Fundamentals & Valuation Matrix
        st.markdown("### Financial Performance & Valuation Matrix")
        f_cols = st.columns(6)
        pe_t = info.get("pe_trailing")
        pe_f = info.get("pe_forward")
        ps = info.get("ps_trailing")
        rev_g = info.get("revenue_growth_yoy")
        profit_m = info.get("profit_margin")
        de = info.get("debt_to_equity")

        f_cols[0].metric("Trailing P/E", f"{pe_t:.1f}×" if pe_t else "—")
        f_cols[1].metric("Forward P/E", f"{pe_f:.1f}×" if pe_f else "—")
        f_cols[2].metric("Price / Sales", f"{ps:.1f}×" if ps else "—")
        f_cols[3].metric("Revenue Growth YoY", f"{rev_g*100:+.1f}%" if rev_g is not None else "—")
        f_cols[4].metric("Profit Margin", f"{profit_m*100:.1f}%" if profit_m is not None else "—")
        f_cols[5].metric("Debt to Equity", f"{de:.1f}" if de is not None else "—")

        st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)

        # Assemble Payload
        mc = market_ctx(include_macro=False)
        payload = ai_payload_from_context(ctx)
        payload["market_regime"] = mc["regime"]
        payload["sector_table"] = mc["sectors"]

        with st.expander("Audit Raw Payload Sent to Gemini (Strict Evidence Rule)", expanded=False):
            st.json(gemini.to_jsonable({k: v for k, v in payload.items() if k != "sector_table"}), expanded=False)

        # AI Action Buttons
        st.markdown("### Gemini AI Research Actions")
        r1, r2 = st.columns(2)
        with r1:
            ui.gemini_panel(
                f"stock_{t}",
                "Full Swing-Trading Research Report",
                lambda: gemini.stock_analysis(t, payload),
                help_text="Evaluates thesis, trend, catalysts, bull/bear cases, invalidation, and eligibility.",
            )
        with r2:
            ui.gemini_panel(
                f"earn_{t}",
                "Earnings & Fundamentals Assessment",
                lambda: gemini.earnings_analysis(
                    t,
                    {
                        "ticker": t,
                        "fundamentals": fund,
                        "days_to_earnings": ctx.get("days_to_earnings"),
                        "price_snapshot": ctx["daily"],
                    },
                ),
                help_text="Deep dive into financial growth, cash flow, debt sustainability, and overnight gap risk.",
            )

with tab_chat:
    st.caption(
        "Interactive Analyst Chat · Grounded in active market data, portfolio equity, and the selected symbol's facts."
    )
    hist = st.session_state.setdefault("chat_history", [])
    for msg in hist:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["text"])

    prompt = st.chat_input("Ask a research question, e.g. 'Compare recent revenue momentum vs price trend'",
                           disabled=not getattr(cfg_app, "ai_configured", getattr(cfg_app, "gemini_configured", False)))
    if prompt:
        hist.append({"role": "user", "text": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Context assembly
        context = {}
        mc = market_ctx(include_macro=False)
        context["market"] = {
            "regime": mc["regime"],
            "indices": mc["indices"],
            "sectors": mc["sectors"],
            "breadth": mc["breadth"],
        }
        acct = account_state(cfg)
        context["account"] = {
            "equity": sizing_equity(acct),
            "cash": acct["cash"],
            "open_risk": acct["open_risk"],
            "risk_per_trade_pct": cfg.risk_per_trade_pct,
            "open_positions": [p.__dict__ for p in acct["open_positions"]],
        }
        if t and valid_ticker(t) and "error" not in ctx:
            context["active_ticker"] = ai_payload_from_context(ctx)

        with st.chat_message("assistant"):
            with st.spinner("Synthesizing evidence..."):
                try:
                    answer = gemini.get_client().chat(hist[:-1], prompt, context)
                except gemini.GeminiError as e:
                    answer = f"⚠️ {e}"
            st.markdown(answer)
        hist.append({"role": "model", "text": answer})

    if hist and st.button("Clear Conversation History", key="_clear_chat_btn"):
        st.session_state["chat_history"] = []
        st.rerun()

with tab_portfolio:
    st.markdown("### Portfolio-Level AI Risk Review")
    acct = account_state(cfg)
    st.markdown(
        f'<div class="term-card">'
        f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
        f'    <span>Open Positions: <strong>{len(acct["open_positions"])}/{cfg.max_positions}</strong></span>'
        f'    <span>Open Portfolio Risk: <strong style="color:#F59E0B;">{ui.money(acct["open_risk"])}</strong></span>'
        f'    <span>Available Cash: <strong style="color:#10B981;">{ui.money(acct["cash"])}</strong></span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    mc = market_ctx(include_macro=False)
    port_payload = {
        "account": {k: v for k, v in acct.items() if k != "open_positions"},
        "positions": [p.__dict__ | {"risk_usd": p.risk} for p in acct["open_positions"]],
        "limits": {
            "risk_per_trade_pct": cfg.risk_per_trade_pct,
            "max_open_risk_pct": cfg.max_open_risk_pct,
            "max_positions": cfg.max_positions,
        },
        "market_regime": mc["regime"],
    }
    ui.gemini_panel(
        "portfolio_risk_review",
        "Generate Institutional Portfolio Risk Review",
        lambda: gemini.risk_review(port_payload),
        help_text="Evaluates concentration risk, correlation overlap, earnings exposures, and risk-reduction steps.",
    )

with tab_audit:
    st.markdown("### AI Report Audit Log")
    st.caption("Complete historical archive of every Gemini synthesis call with full prompt and output auditability.")
    reports = gemini.recent_reports(limit=30)
    if not reports:
        ui.empty_state("No reports in audit log.")
    for r in reports:
        with st.expander(f"{r.created_at:%Y-%m-%d %H:%M} · {r.kind.upper()} · {r.subject} · {r.model}"):
            st.markdown(r.output_text)

ui.disclaimer()
