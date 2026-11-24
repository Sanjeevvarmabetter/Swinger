"""Trade Planner — Institutional Decision Support & Risk Engine."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.risk.engine import floor_to_increment
from tradingos.services import ai_payload_from_context, build_trade_plan, list_plans, save_trade_plan, set_plan_status
from tradingos.ui import charts, components as ui
from tradingos.ui.state import market_ctx, select_ticker, selected_ticker, stock_ctx, valid_ticker

ui.render_top_bar(show_refresh=False)

st.markdown("## Trade Planner & Risk Calculator")
st.caption(
    "Rigorous risk-first trade sizing · Deterministic levels from support/resistance pivots · "
    "AI provides skepticism, not numerical authority · No orders are ever executed."
)

cfg = ui.settings()

# Ticker and Setup Selector
c1, c2, c3 = st.columns([1.5, 1.2, 2.0])
ticker = c1.text_input("Symbol", selected_ticker("")).strip().upper()
hint = st.session_state.get("plan_setup_hint", "")
default_setup = 0 if "Breakout" in hint else 1 if "Pullback" in hint else 2 if "Momentum" in hint else 1
setup = c2.selectbox("Setup Strategy", ["Breakout", "Pullback", "Momentum"], index=default_setup)
holding = c3.text_input("Expected Holding Period", "2–4 weeks")

if not ticker:
    ui.empty_state("Enter an equity or ETF ticker symbol above or select one from the Scanner.")
    st.stop()
if not valid_ticker(ticker):
    st.error("Please enter a valid US ticker symbol.")
    st.stop()
select_ticker(ticker)

with st.spinner(f"Computing levels & position sizing for {ticker}..."):
    ctx = stock_ctx(ticker)
    if "error" in ctx:
        st.error(ctx["error"])
        st.stop()
    mc = market_ctx(include_macro=False)
    base_plan = build_trade_plan(ticker, setup, cfg, ctx=ctx, regime_label=mc["regime"]["label"])

if "error" in base_plan:
    st.error(base_plan["error"])
    st.stop()

ui.freshness_badge(ctx["data_meta"], "Prices")
lv = base_plan["levels"]

st.markdown(
    f'<div style="font-size:0.84rem;color:#94A3B8;margin-bottom:8px;">'
    f'  <strong>Python Proposed Levels (as of {base_plan["data_as_of"]}):</strong> '
    f'  Entry: <strong style="color:#38BDF8;">{ui.money(lv["entry"])}</strong> · '
    f'  Stop: <strong style="color:#F43F5E;">{ui.money(lv["stop"])}</strong> ({lv["stop_basis"]}) · '
    f'  T1: <strong style="color:#10B981;">{ui.money(lv["target1"])}</strong> ({lv["target1_basis"]}) · '
    f'  T2: <strong style="color:#10B981;">{ui.money(lv["target2"])}</strong> ({lv["target2_basis"]})'
    f'</div>',
    unsafe_allow_html=True,
)

with st.expander("Adjust Price Levels (Overrides Recorded For Audit)", expanded=False):
    o1, o2, o3, o4 = st.columns(4)
    entry = o1.number_input("Entry Price ($)", 0.01, value=float(lv["entry"]), step=0.01, format="%.2f")
    stop = o2.number_input("Stop Loss ($)", 0.01, value=float(lv["stop"]), step=0.01, format="%.2f")
    t1 = o3.number_input("Target 1 ($)", 0.01, value=float(lv["target1"]), step=0.01, format="%.2f")
    t2 = o4.number_input("Target 2 ($)", 0.01, value=float(lv["target2"]), step=0.01, format="%.2f")

overrides = {}
for k, v in (("entry", entry), ("stop", stop), ("target1", t1), ("target2", t2)):
    if abs(v - float(lv[k])) > 1e-9:
        overrides[k] = v

plan = build_trade_plan(ticker, setup, cfg, overrides, ctx=ctx, regime_label=mc["regime"]["label"]) if overrides else base_plan
ev = plan["evaluation"]

# -----------------------------------------------------------------------------
# VISUAL TRADE SETUP DIAGRAM (Stop -> Entry -> Target)
# -----------------------------------------------------------------------------
risk_per_sh = ev.size.risk_per_share
reward_per_sh = plan["target1"] - plan["entry"] if plan["target1"] > plan["entry"] else 0.0
pct_risk = (risk_per_sh / plan["entry"] * 100) if plan["entry"] > 0 else 0.0
pct_reward = (reward_per_sh / plan["entry"] * 100) if plan["entry"] > 0 else 0.0

st.markdown(
    f'<div style="background:#0D131F;border:1px solid #1A2436;border-radius:6px;padding:14px 18px;margin:12px 0;">'
    f'  <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;color:#8492A6;text-transform:uppercase;margin-bottom:10px;">'
    f'    Visual Trade Execution Architecture'
    f'  </div>'
    f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
    f'    <div style="text-align:left;min-width:140px;">'
    f'      <div style="font-size:0.70rem;color:#F43F5E;font-weight:700;text-transform:uppercase;">● STOP LOSS</div>'
    f'      <div style="font-family:\'JetBrains Mono\';font-size:1.30rem;color:#F43F5E;font-weight:700;">{ui.money(plan["stop"])}</div>'
    f'      <div style="font-size:0.72rem;color:#94A3B8;font-family:\'JetBrains Mono\';">Risk: -{ui.money(risk_per_sh)} (-{pct_risk:.1f}%)</div>'
    f'    </div>'
    f'    <div style="color:#334155;font-size:1.4rem;padding:0 12px;">──────▶</div>'
    f'    <div style="text-align:center;min-width:140px;">'
    f'      <div style="font-size:0.70rem;color:#38BDF8;font-weight:700;text-transform:uppercase;">● ENTRY TRIGGER</div>'
    f'      <div style="font-family:\'JetBrains Mono\';font-size:1.30rem;color:#38BDF8;font-weight:700;">{ui.money(plan["entry"])}</div>'
    f'      <div style="font-size:0.72rem;color:#94A3B8;font-family:\'JetBrains Mono\';">{ev.size.shares:g} shares · {ui.money(ev.size.position_value)}</div>'
    f'    </div>'
    f'    <div style="color:#334155;font-size:1.4rem;padding:0 12px;">──────▶</div>'
    f'    <div style="text-align:right;min-width:140px;">'
    f'      <div style="font-size:0.70rem;color:#10B981;font-weight:700;text-transform:uppercase;">● PROFIT TARGET 1</div>'
    f'      <div style="font-family:\'JetBrains Mono\';font-size:1.30rem;color:#10B981;font-weight:700;">{ui.money(plan["target1"])}</div>'
    f'      <div style="font-size:0.72rem;color:#94A3B8;font-family:\'JetBrains Mono\';">Reward: +{ui.money(reward_per_sh)} (+{pct_reward:.1f}%)</div>'
    f'    </div>'
    f'  </div>'
    f'</div>',
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# AUTOMATIC RISK & SIZING METRIC TILES
# -----------------------------------------------------------------------------
m_cols = st.columns(4)
m_cols[0].metric("Risk Per Share", ui.money(risk_per_sh), f"-{pct_risk:.1f}%", delta_color="inverse")
m_cols[1].metric("Reward Per Share", ui.money(reward_per_sh), f"+{pct_reward:.1f}%")
m_cols[2].metric("Risk / Reward (T1)", f"{ui.num(ev.rr_t1)}×", f"Net: {ui.num(ev.rr_t1_net)}×")
m_cols[3].metric("Position Size", f"{ev.size.shares:g} shares", ui.money(ev.size.position_value))

m_cols2 = st.columns(4)
m_cols2[0].metric("Total Position Value", ui.money(ev.size.position_value))
m_cols2[1].metric("Max Planned Loss (Net)", ui.money(ev.planned_loss_net), f"Budget: {ui.money(ev.size.risk_budget)}", delta_color="inverse")
m_cols2[2].metric("Potential Net Profit @ T1", ui.money(ev.reward_t1_net), f"T2: {ui.money(plan.get('target2', 0))}")
portfolio_exp_pct = (ev.size.position_value / plan["equity"] * 100) if plan["equity"] > 0 else 0.0
m_cols2[3].metric("Portfolio Exposure", f"{portfolio_exp_pct:.1f}%", f"Equity: {ui.money(plan['equity'])}")

st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# VERDICT & DETAILS
# -----------------------------------------------------------------------------
left, right = st.columns([1.2, 1])

with left:
    st.markdown("### Decision Engine Verdict")
    ui.verdict_badge(ev.verdict)
    for r in ev.verdict_reasons:
        st.markdown(f"- {r}")

    snap = ctx["daily"]
    thesis_default = (
        f"{setup} setup in {ctx['name']} ({ctx['sector']}). Trend: {snap['trend']}; {snap['structure']}. "
        f"RS vs SPY {ui.pct(snap['rs_vs_spy_pp']).replace('%', 'pp')}. "
        + ("Detected: " + "; ".join(snap["setups"]) + "." if snap["setups"] else "No predefined setup detected.")
    )
    thesis = st.text_area("Market Thesis (Why this trade could work)", thesis_default, height=95)
    news_heads = "; ".join(n["headline"] for n in ctx.get("news", [])[:2])
    catalyst = st.text_input("Primary Catalyst / Trigger", news_heads[:200] if news_heads else "")
    dte = ctx.get("days_to_earnings")
    auto_risks = [c.detail for c in ev.checks if not c.passed] + lv["notes"]
    if dte is not None:
        auto_risks.append(f"Earnings in {dte} days.")
    risks = st.text_area("Known Risks & Invalidation Triggers", "\n".join(dict.fromkeys(auto_risks)), height=95)

with right:
    st.markdown("### Risk Engine Checks")
    st.dataframe(
        pd.DataFrame([
            {
                "Status": "✅ Pass" if c.passed else ("⛔ FAIL" if c.severity == "hard" else "⚠️ WARN"),
                "Rule": c.name,
                "Detail": c.detail,
            }
            for c in ev.checks
        ]),
        hide_index=True,
        width="stretch",
    )
    if ev.size.unsuitable:
        st.error("This trade does not fit your risk limit. Skip it or adjust to a tighter valid stop — never increase risk.")

# Interactive Chart with Plan Overlay
st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
st.plotly_chart(
    charts.price_chart(
        ctx["df"],
        ctx["daily"],
        mas=(20, 50, 200),
        bars=150,
        plan={
            "entry": plan["entry"],
            "stop": plan["stop"],
            "target1": plan["target1"],
            "target2": plan["target2"],
        },
        title=f"{ticker} Trade Plan Levels · Entry, Stop & Targets",
    ),
    width="stretch",
)

# Gemini Trade Review
st.markdown("### AI Risk Review & Strategy Critique")
payload = {
    "plan": {
        "ticker": ticker,
        "setup": setup,
        "thesis": thesis,
        "catalyst": catalyst,
        "risks": risks,
        "holding_period": holding,
        "levels": lv,
        "entry": plan["entry"],
        "stop": plan["stop"],
        "target1": plan["target1"],
        "target2": plan["target2"],
        "user_overrides": overrides,
    },
    "risk_engine": ev.as_dict(),
    "market_regime": mc["regime"],
    "stock": ai_payload_from_context(ctx),
}

ui.gemini_panel(
    f"plan_{ticker}_{setup}",
    "Generate AI Trade Review & Strategic Critique",
    lambda: gemini.trade_plan_review(ticker, payload),
    help_text="Critiques thesis, stop placement validity, R:R justification, and potential failure modes.",
)

# Save & Execute Plan Actions
s1, s2, _ = st.columns([1.2, 1.5, 2.5])
with s1:
    if st.button("💾 Save Trade Plan", type="primary", width="stretch"):
        pid = save_trade_plan(
            plan,
            thesis,
            catalyst,
            risks,
            holding,
            st.session_state.get(f"ai_plan_{ticker}_{setup}") or "",
        )
        st.success(f"Plan #{pid} saved with verdict '{ev.verdict}'.")

with s2:
    if st.button("Direct to Journal (Record Fill) →", width="stretch"):
        st.session_state["journal_prefill"] = {
            "plan_id": None,
            "ticker": ticker,
            "setup": setup,
            "entry": plan["entry"],
            "stop": plan["stop"],
            "target1": plan["target1"],
            "target2": plan["target2"],
            "shares": ev.size.shares,
            "thesis": thesis,
        }
        st.switch_page("views/journal.py")

# Saved Plans List
st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
st.markdown("### Active Saved Trade Plans")
plans = list_plans("ACTIVE")
if plans.empty:
    ui.empty_state("No active saved plans.")
else:
    st.dataframe(plans.drop(columns=["thesis", "status"]), hide_index=True, width="stretch")
    p1, p2, p3 = st.columns([1.5, 1.2, 1.0])
    with p1:
        pid = p1.selectbox("Select Plan", plans["id"], format_func=lambda i: f"#{i} {plans.set_index('id').loc[i, 'ticker']}")
    with p2:
        if st.button("Fill in Journal →", width="stretch"):
            row = plans.set_index("id").loc[pid]
            st.session_state["journal_prefill"] = {
                "plan_id": int(pid),
                "ticker": row["ticker"],
                "setup": row["setup"],
                "entry": row["entry"],
                "stop": row["stop"],
                "target1": row["target1"],
                "target2": row["target2"],
                "shares": row["shares"],
                "thesis": row["thesis"],
            }
            st.switch_page("views/journal.py")
    with p3:
        if st.button("Cancel Plan", width="stretch"):
            set_plan_status(int(pid), "CANCELLED")
            st.rerun()

ui.disclaimer()
