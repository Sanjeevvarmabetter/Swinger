from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.data.providers import get_market_provider
from tradingos.journal import service as js
from tradingos.performance import metrics as pm
from tradingos.performance.backtest import BTParams, run_backtest
from tradingos.services import latest_prices
from tradingos.ui import charts, components as ui
from tradingos.ui.state import selected_ticker, valid_ticker

ui.render_top_bar(show_refresh=False)

st.markdown("## Performance Analytics & Portfolio Returns")
st.caption("Quantitative audit of trading results · Equity curve & drawdown analytics · Setup & sector attribution · Indian tax compliance")

cfg = ui.settings()
trades = js.trades_dataframe()
closed = trades[trades["status"] == "CLOSED"] if len(trades) else trades
flows = js.capital_flows_dataframe()
opn = trades[trades["status"] == "OPEN"] if len(trades) else trades
prices, pmeta = latest_prices(list(opn["ticker"].unique()) if len(opn) else [])
acct = js.account_state(cfg, prices)

tab_perf, tab_review, tab_tax, tab_bt = st.tabs(
    ["Dashboard & Analytics", "Weekly / Monthly AI Review", "🇮🇳 Indian Tax Report", "Strategy Backtest"])

with tab_perf:
    m = pm.core_metrics(closed) if len(closed) else {"trades": 0}
    k = st.columns(5)
    k[0].metric("Total contributed", ui.money(acct["net_contributed"]))
    k[1].metric("Current trading equity", ui.money(js.sizing_equity(acct)),
                help="Marked to latest close when all open positions are priced; otherwise at cost.")
    k[2].metric("Realized P&L", ui.money(acct["realized_pnl"]))
    k[3].metric("Unrealized P&L", ui.money(acct["unrealized_pnl"]) if acct["unrealized_pnl"] is not None else "n/a",
                help="Requires a current price for every open position.")
    k[4].metric("Closed trades", m["trades"])
    if pmeta:
        ui.freshness_badge(pmeta, "Valuation prices")
    warn = pm.sample_warning(m["trades"], cfg)
    if warn:
        st.warning(warn)
    if m["trades"] == 0:
        ui.empty_state("No closed trades yet — analytics appear after your first completed trade.")
    else:
        k = st.columns(6)
        k[0].metric("Win rate", ui.pct(m["win_rate_pct"], 1, False))
        k[1].metric("Avg winner", ui.money(m["avg_winner"]))
        k[2].metric("Avg loser", ui.money(m["avg_loser"]))
        k[3].metric("Profit factor", ui.num(m["profit_factor"]))
        k[4].metric("Expectancy / trade", ui.money(m["expectancy_usd"]), f"{ui.num(m['expectancy_r'])} R",
                    delta_color="off")
        k[5].metric("Avg hold (days)", ui.num(m["avg_holding_days"], 1))
        curve = pm.equity_curve(closed, flows, cfg.starting_capital_usd)
        dd = pm.max_drawdown(curve)
        k = st.columns(3)
        k[0].metric("Max drawdown", ui.pct(dd["max_drawdown_pct"], 2), ui.money(dd["max_drawdown_usd"]), delta_color="off")
        k[1].metric("Total fees & costs", ui.money(m["total_fees"]))
        k[2].metric("Avg R-multiple", ui.num(m["avg_r"]))
        if not curve.empty:
            st.plotly_chart(charts.line_chart({"Account equity (incl. transfers)": curve["account_equity"],
                                               "Performance equity (excl. transfers)": curve["performance_equity"]},
                                              "Equity curve (realized)", 300), width="stretch")
            st.plotly_chart(charts.drawdown_chart(curve["drawdown_pct"]), width="stretch")
        a, b = st.columns(2)
        with a:
            st.markdown("**Monthly returns**")
            st.dataframe(pm.monthly_returns(closed, curve), hide_index=True, width="stretch")
            st.markdown("**By setup**")
            st.dataframe(pm.breakdown(closed, "setup"), hide_index=True, width="stretch")
        with b:
            st.markdown("**By sector**")
            st.dataframe(pm.breakdown(closed, "sector"), hide_index=True, width="stretch")
            r = closed["r_multiple"].dropna()
            if len(r):
                import plotly.express as px
                fig = px.histogram(r, nbins=20, title="R-multiple distribution")
                st.plotly_chart(charts._layout(fig, 260), width="stretch")
    st.subheader("Process diagnostics")
    diag = pm.diagnostics(trades, cfg) if len(trades) else {}
    labels = {"risk_violations": "Risk-management violations", "stop_widened": "Stops moved wider",
              "poor_entries": "Poor entries (chased > 1% above plan)", "possible_early_exits": "Possible early exits",
              "loss_exceeded_plan": "Losses bigger than planned (> 1.2R)", "overtrading_months": "Overtrading",
              "mistake_tags": "Self-tagged mistakes"}
    any_flag = False
    for k_, lbl in labels.items():
        items = diag.get(k_, [])
        if items:
            any_flag = True
            with st.expander(f"{lbl} ({len(items)})"):
                for i in items:
                    st.markdown(f"- {i}")
    if not any_flag:
        st.caption("No process flags. (Heuristics: review your own trades too.)")
    if m["trades"] >= 1:
        bs = pm.breakdown(closed, "setup")
        if len(bs) > 1 and not warn:
            st.markdown(f"Best setup so far: **{bs.iloc[0]['setup']}** · weakest: **{bs.iloc[-1]['setup']}**")

with tab_review:
    period = st.radio("Period", ["Last 7 days", "Last 30 days", "Custom"], horizontal=True)
    end = datetime.now()
    start = end - timedelta(days=7 if period == "Last 7 days" else 30)
    if period == "Custom":
        c1, c2 = st.columns(2)
        start = datetime.combine(c1.date_input("From", start.date()), datetime.min.time())
        end = datetime.combine(c2.date_input("To", end.date()), datetime.max.time())
    rev = pm.period_review(trades, start, end, cfg)
    st.markdown(f"**{rev['period']}** — opened {rev['opened']}, closed {rev['closed']}")
    if rev.get("sample_warning"):
        st.caption(rev["sample_warning"])
    if rev.get("metrics"):
        st.json(rev["metrics"], expanded=False)
    if rev.get("closed_trades"):
        st.dataframe(pd.DataFrame(rev["closed_trades"]), hide_index=True, width="stretch")
    ui.gemini_panel(f"review_{period}", "Gemini performance review",
                    lambda: gemini.weekly_performance_review(rev))

with tab_tax:
    st.markdown("### 🇮🇳 Indian Capital Gains Tax Report (Schedule CG & Schedule FA)")
    st.caption("Calculates financial-year realized capital gains in Indian Rupees (INR) from US swing trades. "
               "Foreign equities held ≤ 24 months (730 days) are treated as Short-Term Capital Gains (STCG), "
               "taxable at applicable slab rates. Equities held > 24 months are treated as Long-Term Capital Gains (LTCG). "
               "Exchange rates are looked up from historical USD/INR on transaction dates.")

    from tradingos.tax.indian_tax import compute_indian_tax_report, fy_for_date

    if closed.empty:
        ui.empty_state("No closed trades yet to calculate capital gains.")
    else:
        available_fys = sorted(
            list(dict.fromkeys(fy_for_date(pd.to_datetime(d).date()) for d in closed["exit_date"].dropna())),
            reverse=True,
        )
        if not available_fys:
            available_fys = ["FY 2026-27", "FY 2025-26", "FY 2024-25"]

        f1, f2, f3 = st.columns(3)
        selected_fy = f1.selectbox("Financial Year", ["All"] + available_fys, index=0)
        custom_fx = f2.number_input("Custom USD/INR rate override (0 = auto historical)", 0.0, 200.0, 0.0, 0.5,
                                    help="Set to 0 to look up historical exchange rates on transaction dates automatically.")
        slab_pct = f3.number_input("Estimated slab tax rate %", 0.0, 50.0, float(cfg.est_tax_rate_pct), 1.0)

        tax_rep = compute_indian_tax_report(
            closed,
            fy=selected_fy,
            fx_override=custom_fx if custom_fx > 0 else None,
            est_slab_rate_pct=slab_pct,
        )

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Closed Trades", tax_rep.trades_count)
        k2.metric("Sale Proceeds", f"₹{tax_rep.total_proceeds_inr:,.0f}")
        k3.metric("Cost of Acquisition", f"₹{tax_rep.total_cost_inr:,.0f}")
        k4.metric("Allowable Expenses", f"₹{tax_rep.total_fees_inr:,.0f}")

        k5, k6, k7 = st.columns(3)
        k5.metric("Net STCG (≤24m)", f"₹{tax_rep.net_stcg_inr:,.0f}", delta_color="normal" if tax_rep.net_stcg_inr >= 0 else "inverse")
        k6.metric("Net LTCG (>24m)", f"₹{tax_rep.net_ltcg_inr:,.0f}", delta_color="normal" if tax_rep.net_ltcg_inr >= 0 else "inverse")
        k7.metric("Est. Tax Liability", f"₹{tax_rep.est_slab_tax_inr:,.0f}", f"at {slab_pct:g}% slab rate", delta_color="off")

        tax_df = tax_rep.to_dataframe()
        if not tax_df.empty:
            st.dataframe(tax_df, hide_index=True, width="stretch")
            st.download_button(
                f"⬇ Download Indian Tax Report CSV ({selected_fy})",
                tax_df.to_csv(index=False),
                file_name=f"indian_tax_report_{selected_fy.replace(' ', '_')}.csv",
                mime="text/csv",
                type="primary",
            )
        else:
            ui.empty_state(f"No trades closed in {selected_fy}.")

        st.caption("ℹ️ Disclaimer: This report is a computational helper based on recorded broker fills and exchange rates. "
                   "It does not constitute formal tax advice. Consult a Chartered Accountant (CA) for filing ITR-2 or ITR-3.")

with tab_bt:
    st.caption("Sanity-check the app's own setup rules on one ticker. Entries next open, stop checked before target, "
               "costs per side applied. Caveats: survivorship bias, adjusted prices, small samples, no regime filter. "
               "Past results do not validate future edge.")
    c1, c2, c3, c4, c5 = st.columns(5)
    t = c1.text_input("Ticker", selected_ticker("SPY") or "SPY").strip().upper()
    rule = c2.selectbox("Rule", ["pullback", "breakout", "momentum"])
    stop_m = c3.number_input("Stop (× ATR)", 0.5, 5.0, 2.0, 0.25)
    tgt = c4.number_input("Target (R)", 0.5, 6.0, 2.0, 0.25)
    hold = c5.number_input("Max hold (days)", 3, 60, 20)
    if st.button("Run backtest") and valid_ticker(t):
        res = get_market_provider().history([t], period="10y")
        if not res.ok or t not in res.data:
            st.error(res.error or "No data")
        else:
            bt, stats = run_backtest(res.data[t], BTParams(rule, stop_m, tgt, int(hold)))
            ui.freshness_badge(res.meta(), "Prices")
            st.write(stats)
            if stats.get("trades", 0) < 30:
                st.warning(f"Only {stats.get('trades', 0)} trades — not statistically meaningful.")
            if len(bt):
                st.plotly_chart(charts.line_chart({"Cumulative R": bt.set_index(pd.to_datetime(bt["exit_date"]))["r"].cumsum()},
                                                  f"{t} {rule}: cumulative R", 280), width="stretch")
                st.dataframe(bt, hide_index=True, width="stretch")
ui.disclaimer()
