from datetime import date, datetime, time

import streamlit as st

from tradingos.db.session import backup_databases, restore_note
from tradingos.journal import service as js
from tradingos.risk.engine import position_size
from tradingos.services import latest_prices, ticker_meta
from tradingos.ui import components as ui
from tradingos.ui.state import valid_ticker

ui.render_top_bar(show_refresh=False)

st.markdown("## Trading Journal & Execution Log")
cfg = ui.settings()
acct = js.account_state(cfg)
equity = js.sizing_equity(acct)

# Account metric tiles
j_cols = st.columns(4)
j_cols[0].metric("Trading Equity (Cost)", ui.money(acct["equity_at_cost"]))
j_cols[1].metric("Available Cash", ui.money(acct["cash"]))
j_cols[2].metric("Realized P&L", ui.money(acct["realized_pnl"]))
j_cols[3].metric("Open Trades", f"{len(acct['open_positions'])}/{cfg.max_positions}")

st.caption("Active swing trading account · Capital is segregated from long-term investments.")

ui.show_flash()
pre = st.session_state.get("journal_prefill")
if pre:
    st.info(f"🎯 **Draft trade ready to record:** Plan #{pre.get('plan_id')} for **{pre.get('ticker')}** ({pre.get('setup')}). "
            f"Click the **'Record new trade'** tab below to enter your actual fill.")

new_tab_label = "Record new trade (Draft Ready 🔴)" if pre else "Record new trade"
tab_open, tab_new, tab_closed, tab_cap, tab_import, tab_export = st.tabs(
    ["Open trades", new_tab_label, "Closed trades", "Capital ledger", "Import CSV (Vested)", "Export & backup"])

# ------------------------------------------------------------------ new trade
with tab_new:
    pre = st.session_state.get("journal_prefill", {})
    if pre:
        st.info(f"Prefilled from plan #{pre['plan_id']} ({pre['ticker']}). Enter your ACTUAL broker fill.")
    with st.form("new_trade"):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker", pre.get("ticker", "")).strip().upper()
        setups = js.SETUPS
        setup = c2.selectbox("Setup", setups, index=setups.index(pre["setup"]) if pre.get("setup") in setups else 0)
        filled_date = c3.date_input("Fill date", date.today())
        thesis = st.text_area("Entry thesis (required, locked after saving)", pre.get("thesis", ""), height=100)
        c1, c2, c3, c4 = st.columns(4)
        planned = c1.number_input("Planned entry", 0.0, value=float(pre.get("entry", 0.0)), step=0.01, format="%.2f")
        stop = c2.number_input("Initial stop", 0.0, value=float(pre.get("stop", 0.0)), step=0.01, format="%.2f")
        t1 = c3.number_input("Target 1", 0.0, value=float(pre.get("target1") or 0.0), step=0.01, format="%.2f")
        t2 = c4.number_input("Target 2", 0.0, value=float(pre.get("target2") or 0.0), step=0.01, format="%.2f")
        c1, c2, c3, c4, c5 = st.columns(5)
        fill = c1.number_input("Actual fill price", 0.0, value=float(pre.get("entry", 0.0)), step=0.01, format="%.4f")
        qty = c2.number_input("Quantity", 0.0, value=float(pre.get("shares", 0.0)), step=float(cfg.share_increment),
                              format="%.4f")
        comm = c3.number_input("Commission $", 0.0, value=0.0, step=0.01)
        fx = c4.number_input("FX cost $", 0.0, value=0.0, step=0.01)
        other = c5.number_input("Other costs $", 0.0, value=0.0, step=0.01)
        entry_chart = st.file_uploader("Attach entry chart screenshot (optional)", type=["png", "jpg", "jpeg", "webp"], key="new_chart")
        ack = st.checkbox("I acknowledge this trade's risk exceeds my configured limit (it will be flagged).")
        submitted = st.form_submit_button("Save trade", type="primary")
    if submitted:
        errors = []
        if not valid_ticker(ticker):
            errors.append("Invalid ticker.")
        if fill <= 0 or qty <= 0 or stop <= 0:
            errors.append("Fill, quantity and stop must be positive.")
        if not thesis.strip():
            errors.append("Write the entry thesis first.")
        risk = (fill - stop) * qty + comm + fx + other
        allowed = equity * cfg.risk_per_trade_pct / 100
        if not errors and risk > allowed * 1.10 and not ack:
            sz = position_size(equity, cfg.risk_per_trade_pct, fill, stop, cfg.share_increment)
            errors.append(f"Risk ${risk:.2f} exceeds your budget ${allowed:.2f}. Risk-sized quantity would be "
                          f"{sz.shares:g}. Reduce size, or tick the acknowledgement to record it as a violation.")
        if not errors and acct["open_risk"] + max(0, risk) > equity * cfg.max_open_risk_pct / 100 * 1.10 and not ack:
            errors.append("This would push aggregate open risk above your limit. Tick acknowledgement to record anyway.")
        for e in errors:
            st.error(e)
        if not errors:
            try:
                tid = js.open_trade(ticker=ticker, setup=setup, entry_thesis=thesis, planned_entry=planned or fill,
                                    initial_stop=stop, target1=t1 or None, target2=t2 or None, fill_price=fill, qty=qty,
                                    filled_at=datetime.combine(filled_date, time(16, 0)), commission=comm, fx_cost=fx,
                                    other_costs=other, sector=ticker_meta(ticker)["sector"],
                                    plan_id=pre.get("plan_id"), cfg=cfg, equity=equity)
                if entry_chart:
                    from tradingos.journal.screenshots import save_screenshot
                    s_path = save_screenshot(tid, entry_chart.getvalue(), entry_chart.name)
                    js.update_reflection(tid, chart_ref=s_path)
                st.session_state.pop("journal_prefill", None)
                st.success(f"Trade #{tid} recorded. The thesis is now locked.")
            except ValueError as e:
                st.error(str(e))

# ------------------------------------------------------------------ open trades
with tab_open:
    opn = js.trades_dataframe("OPEN")
    if opn.empty:
        ui.empty_state("No open trades.")
    else:
        prices, pmeta = latest_prices(list(opn["ticker"].unique()))
        opn["last"] = opn["ticker"].map(prices)
        opn["unrealized"] = ((opn["last"] - opn["avg_entry"]) * opn["open_qty"]).round(2)
        opn["R now"] = ((opn["last"] - opn["avg_entry"]) / (opn["avg_entry"] - opn["initial_stop"])).round(2)
        st.dataframe(opn[["id", "ticker", "setup", "entry_date", "avg_entry", "open_qty", "initial_stop",
                          "current_stop", "target", "last", "unrealized", "R now", "realized_net", "holding_days"]],
                     hide_index=True, width="stretch")
        if pmeta:
            ui.freshness_badge(pmeta, "Last prices")
        tid = st.selectbox("Manage trade", opn["id"], format_func=lambda i: f"#{i} {opn.set_index('id').loc[i, 'ticker']}")
        tr = opn.set_index("id").loc[tid]
        with st.container(border=True):
            st.markdown("🔒 **Original thesis (immutable)**")
            st.markdown(tr["entry_thesis"])
            st.caption(f"Planned entry {tr['planned_entry']} · initial stop {tr['initial_stop']} · target {tr['target']} "
                       f"· risk {tr['planned_risk_pct']}% of {ui.money(tr['equity_at_entry'])} equity at entry")
            if tr.get("chart_ref"):
                ref = str(tr["chart_ref"]).strip()
                from pathlib import Path
                if ref.startswith("http://") or ref.startswith("https://") or Path(ref).exists():
                    st.image(ref, caption=f"Chart setup #{tid} ({tr['ticker']})")
        a, b = st.columns(2)
        with a.form(f"exit_{tid}", clear_on_submit=True):
            st.markdown("**Record exit (partial or full)**")
            x1, x2, x3 = st.columns(3)
            q = x1.number_input("Qty", 0.0, float(tr["open_qty"]), float(tr["open_qty"]), step=float(cfg.share_increment), format="%.4f")
            px = x2.number_input("Price", 0.0, value=float(prices.get(tr["ticker"], tr["avg_entry"])), step=0.01, format="%.4f")
            dt = x3.date_input("Date", date.today())
            y1, y2 = st.columns(2)
            comm = y1.number_input("Commission $", 0.0, value=0.0, step=0.01)
            fxc = y2.number_input("FX cost $", 0.0, value=0.0, step=0.01)
            reason = st.selectbox("Exit reason", ["Target 1 hit (planned profit booking)", "Target 2 hit",
                                                  "Stop hit", "Trailing stop", "Time stop", "Thesis invalidated",
                                                  "Pre-earnings exit", "Discretionary / other"])
            note = st.text_input("Note")
            if st.form_submit_button("Save exit"):
                try:
                    r = js.record_exit(int(tid), qty=q, price=px, filled_at=datetime.combine(dt, time(16, 0)),
                                       commission=comm, fx_cost=fxc, note=note, exit_reason=f"{reason}. {note}".strip())
                    ui.flash(f"Exit saved. Status {r['status']}, open qty {r['open_qty']:g}, realized {ui.money(r['realized_net'])}.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        with b.form(f"stop_{tid}", clear_on_submit=True):
            st.markdown("**Move stop**")
            ns = st.number_input("New stop", 0.0, value=float(tr["current_stop"]), step=0.01, format="%.2f")
            why = st.text_input("Reason (e.g. moved to breakeven after T1)")
            if ns < tr["current_stop"]:
                st.warning("This WIDENS the stop (increases risk). It will be flagged in analytics.")
            if st.form_submit_button("Update stop"):
                try:
                    r = js.change_stop(int(tid), ns, why)
                    ui.flash(f"Stop {r['old']:.2f} → {r['new']:.2f}" + (" (flagged: widened)" if r["widened"] else ""),
                             "warning" if r["widened"] else "success")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

# ------------------------------------------------------------------ closed
with tab_closed:
    cl = js.trades_dataframe("CLOSED")
    if cl.empty:
        ui.empty_state("No closed trades yet.")
    else:
        st.dataframe(cl[["id", "ticker", "setup", "sector", "entry_date", "exit_date", "avg_entry", "avg_exit", "qty",
                         "fees_total", "realized_net", "r_multiple", "holding_days", "exit_reason", "mistake_tags"]],
                     hide_index=True, width="stretch")
        tid = st.selectbox("Review trade", cl["id"], format_func=lambda i: f"#{i} {cl.set_index('id').loc[i, 'ticker']}")
        tr = cl.set_index("id").loc[tid]
        st.markdown(f"🔒 **Original thesis:** {tr['entry_thesis']}")
        st.markdown(f"**Exit log:** {tr['exit_reason'] or '—'}")
        if tr.get("chart_ref"):
            ref = str(tr["chart_ref"]).strip()
            from pathlib import Path
            if ref.startswith("http://") or ref.startswith("https://") or Path(ref).exists():
                st.image(ref, caption=f"Chart screenshot #{tid} ({tr['ticker']})")

        with st.form(f"reflect_{tid}"):
            lessons = st.text_area("Lessons learned", tr["lessons"] or "")
            chart = st.text_input("Screenshot / chart reference (path or URL)", tr["chart_ref"] or "")
            up_chart = st.file_uploader("Upload new chart screenshot", type=["png", "jpg", "jpeg", "webp"], key=f"cl_chart_{tid}")
            tags = st.multiselect("Mistake tags", js.MISTAKE_TAGS,
                                  default=[t for t in (tr["mistake_tags"] or "").split(",") if t in js.MISTAKE_TAGS])
            if st.form_submit_button("Save reflection"):
                final_chart = chart
                if up_chart:
                    from tradingos.journal.screenshots import save_screenshot
                    final_chart = save_screenshot(int(tid), up_chart.getvalue(), up_chart.name)
                js.update_reflection(int(tid), lessons=lessons, chart_ref=final_chart, mistake_tags=tags)
                ui.flash("Reflection saved.")
                st.rerun()
    st.caption("Reflection fields are editable; the original thesis, plan levels and fills are not.")
    opn_all = js.trades_dataframe("OPEN")
    if len(opn_all):
        with st.expander("Add reflection/tags to an OPEN trade"):
            tid2 = st.selectbox("Open trade", opn_all["id"], key="refl_open")
            tags2 = st.multiselect("Mistake tags", js.MISTAKE_TAGS, key="tags_open")
            note2 = st.text_area("Notes", key="notes_open")
            if st.button("Save", key="save_open_refl"):
                js.update_reflection(int(tid2), lessons=note2, mistake_tags=tags2)
                st.success("Saved.")

# ------------------------------------------------------------------ capital
with tab_cap:
    st.caption("Record transfers INTO and OUT OF the swing-trading account only. Long-term investments live in a "
               "separate database and are never part of trading equity.")
    with st.form("flow", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        kind = c1.selectbox("Type", ["DEPOSIT", "WITHDRAWAL"])
        amt = c2.number_input("Amount (USD received/sent)", 0.0, step=10.0)
        inr = c3.number_input("INR amount (optional)", 0.0, step=1000.0)
        fxc = c4.number_input("FX/transfer cost (USD)", 0.0, step=0.5)
        d = c5.date_input("Date", date.today())
        notes = st.text_input("Notes")
        if st.form_submit_button("Add") and amt > 0:
            js.add_capital_flow(kind, amt, d, inr or None, (inr / amt) if inr else None, fxc, notes)
            ui.flash(f"{kind.title()} of {ui.money(amt)} recorded.")
            st.rerun()
    flows = js.capital_flows_dataframe()
    if len(flows):
        st.dataframe(flows, hide_index=True, width="stretch")
    else:
        ui.empty_state(f"No transfers yet. Starting capital ({ui.money(cfg.starting_capital_usd)}) is set in Settings.")
    m = st.columns(4)
    m[0].metric("Starting capital", ui.money(acct["starting_capital"]))
    m[1].metric("Net deposits", ui.money(acct["deposits"] - acct["withdrawals"]))
    m[2].metric("Transfer FX costs", ui.money(acct["fx_costs_on_transfers"]))
    m[3].metric("Equity at cost", ui.money(acct["equity_at_cost"]))

# ------------------------------------------------------------------ import CSV
with tab_import:
    st.markdown("### Import Trades from CSV (Vested / DriveWealth / Generic)")
    st.caption("Import trade confirmation reports and account statement CSVs directly into your journal. "
               "Supported broker formats: Vested activity exports, DriveWealth trade confirmations, or standard TradingOS format.")

    from tradingos.journal.importer import execute_import, generate_template_csv, parse_trades_csv

    t1, t2 = st.columns([1, 2])
    with t1:
        st.download_button("⬇ Download CSV template", generate_template_csv(), "trades_template.csv", mime="text/csv",
                           help="Standard CSV columns: ticker, side (BUY/SELL), date, qty, price, commission, fx_cost, other_costs, notes")

    uploaded_csv = st.file_uploader("Upload broker CSV statement", type=["csv"], key="broker_csv_uploader")
    if uploaded_csv is not None:
        raw_bytes = uploaded_csv.getvalue()
        parsed_fills, warnings = parse_trades_csv(raw_bytes)
        for w in warnings:
            st.warning(w)

        if parsed_fills:
            valid_fills = [f for f in parsed_fills if not f.error]
            invalid_fills = [f for f in parsed_fills if f.error]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total rows", len(parsed_fills))
            m2.metric("Valid fills", len(valid_fills))
            m3.metric("Invalid rows", len(invalid_fills))
            tot_val = sum(f.qty * f.price for f in valid_fills)
            m4.metric("Total volume", ui.money(tot_val))

            preview_data = [f.to_dict() for f in parsed_fills]
            preview_df = pd.DataFrame(preview_data)
            preview_df["Status"] = ["❌ Error: " + str(r["error"]) if r["error"] else "✅ Ready" for r in preview_data]

            st.markdown("**Preview Parsed Fills:**")
            st.dataframe(preview_df.drop(columns=["error"]), hide_index=True, width="stretch")

            if invalid_fills:
                st.warning(f"{len(invalid_fills)} row(s) contain errors and will be skipped.")

            if valid_fills and st.button(f"📥 Import {len(valid_fills)} Valid Fill(s) into Journal", type="primary"):
                result = execute_import(parsed_fills, cfg)
                for err in result["errors"]:
                    st.error(err)
                ui.flash(f"Successfully imported {result['imported_fills']} fill(s) "
                         f"({result['new_trades']} new trade(s) opened, {result['exits_recorded']} exit(s) recorded).")
                st.rerun()

# ------------------------------------------------------------------ export
with tab_export:
    all_t = js.trades_dataframe()
    st.download_button("⬇ Trades CSV", all_t.to_csv(index=False), "trades.csv", disabled=all_t.empty)
    fills = js.fills_dataframe()
    st.download_button("⬇ Fills CSV", fills.to_csv(index=False), "fills.csv", disabled=fills.empty)
    fl = js.capital_flows_dataframe()
    st.download_button("⬇ Capital flows CSV", fl.to_csv(index=False), "capital_flows.csv", disabled=fl.empty)
    st.divider()
    if st.button("Back up databases now"):
        made = backup_databases()
        st.success("Backups: " + ", ".join(p.name for p in made))
    st.caption("An automatic backup is taken once per day when the app starts (last 30 kept). " + restore_note())
ui.disclaimer()
