"""Economic Calendar & Central Bank Tracker — official schedules, IST times, sourced readings only."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.db.models import EconEvent
from tradingos.db.session import session_scope
from tradingos.intel import calendars
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=False)
iu.page_header("Economic Calendar & Central Banks", "US releases (FRED official schedule) · FOMC (federalreserve.gov) · "
               "your sourced entries for RBI/ECB/BoJ/BoE/China · times in IST · actuals only when officially released")

st.caption("No forecasts or consensus numbers are shown: the current Finnhub/FMP plans do not include an economic "
           "calendar (verified on System Health) and the app never estimates them. 'Previous' and 'Actual' come from "
           "FRED series data with their reference periods.")

with st.expander("Filters", icon=":material/filter_list:"):
    c1, c2, c3, c4 = st.columns([1, 1, 1.4, 1])
past = c1.selectbox("Look back", [3, 7, 14, 30], index=2, format_func=lambda d: f"{d} days")
ahead = c2.selectbox("Look ahead", [7, 14, 30, 60], index=2, format_func=lambda d: f"{d} days")
imp = c3.multiselect("Importance", ["high", "medium", "low"], default=["high", "medium"])
countries = c4.multiselect("Country", ["US", "IN", "EU", "UK", "JP", "CN", "Other"], default=[])

with st.spinner("Loading official schedules…"):
    cal, errs = calendars.economic_calendar(past, ahead)
for e in errs:
    st.warning(e)

tab_cal, tab_cb, tab_add, tab_ai = st.tabs(["Calendar", "Central bank tracker", "Add a sourced event", "AI preview"])

with tab_cal:
    if cal.empty:
        ui.empty_state("No events in the window.")
    else:
        d = cal[cal["importance"].isin(imp)] if imp else cal
        if countries:
            d = d[d["country"].isin(countries) | (("Other" in countries) & ~d["country"].isin(["US", "IN", "EU", "UK", "JP", "CN"]))]
        today = date.today()
        for label, part in (("Upcoming", d[d["date"] >= today]), ("Recent", d[d["date"] < today].iloc[::-1])):
            st.markdown(f"#### {label} ({len(part)})")
            if part.empty:
                ui.empty_state("Nothing here.")
                continue
            for _, r in part.iterrows():
                imp_cls = {"high": "tos-red", "medium": "tos-amber"}.get(r["importance"], "")
                when = "today" if r["date"] == today else f"{(r['date'] - today).days:+d}d"
                head = (f"{r['date']:%a %d %b} ({when}) · {r['time_ist']} · {r['country']} · {r['event']}")
                with st.expander(head, expanded=r["importance"] == "high" and 0 <= (r["date"] - today).days <= 3):
                    st.markdown(f"{ui.chip(r['importance'].upper(), imp_cls)} {ui.chip(r['origin'])} "
                                f"<a href='{r['source']}' target='_blank' style='color:#4EA8F2;font-size:0.8rem;'>source ↗</a>",
                                unsafe_allow_html=True)
                    if r.get("market_relevance"):
                        st.caption(f"Why it matters (framework): {r['market_relevance']}")
                    if pd.notna(r.get("rid")):
                        rd = calendars.release_readings(int(r["rid"]), r["date"], superseded=bool(r.get("superseded")))
                        rows = [{"Indicator": x["indicator"], "Reference period": x.get("reference_period"),
                                 "Actual": x.get("actual") or "—", "Previous": x.get("previous") or "—",
                                 "Forecast": "n/a", "Status": x.get("status", x.get("error", "")),
                                 "FRED": x.get("series")} for x in rd]
                        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                                     column_config={"FRED": st.column_config.LinkColumn("Series", display_text="FRED ↗")})
                    if r["origin"] == "manual" and pd.notna(r.get("id")):
                        if st.button("Delete this entry", key=f"del_{int(r['id'])}"):
                            with session_scope() as s:
                                ev = s.get(EconEvent, int(r["id"]))
                                if ev:
                                    s.delete(ev)
                            st.rerun()
        st.caption("Usual release times are each agency's standard schedule (e.g. BLS 08:30 ET) converted to IST with "
                   "daylight saving; agencies occasionally change them. FOMC decision = 14:00 ET on the last meeting day.")

with tab_cb:
    with st.spinner("Loading policy rates and official communications…"):
        cbs = calendars.central_bank_tracker()
    fomc = calendars.fomc_meetings()
    nxt = fomc.data[fomc.data["decision_date"] >= date.today()].head(1) if fomc.ok else pd.DataFrame()
    for cb in cbs:
        with st.container(border=True):
            a, b = st.columns([1, 2])
            with a:
                st.markdown(f"**{cb['bank']}**")
                if cb.get("rate") is not None:
                    st.metric(cb["rate_label"], f"{cb['rate']:.2f}%", help=f"As of {cb['rate_as_of']}")
                    st.caption(f"Last change: {cb['last_change']} · [FRED ↗]({cb['rate_source']})")
                else:
                    st.caption(f"{cb['rate_label']} — see [official page ↗]({cb['official']})")
                if cb["bank"] == "Federal Reserve" and len(nxt):
                    n = nxt.iloc[0]
                    st.caption(f"Next FOMC decision: **{n['decision_date']:%a %d %b %Y}** ({n['time_ist']})"
                               + (" · projections + press conference" if n["sep"] else ""))
                elif cb["bank"] != "Federal Reserve":
                    st.caption("Next meeting: add it from the bank's official calendar in *Add a sourced event*.")
            with b:
                comms = cb.get("latest_communications") or []
                if comms:
                    for c in comms:
                        tag = " · _routine_" if c["routine"] else ""
                        st.markdown(f"- [{c['headline']}]({c['url']}) — {pd.Timestamp(c['published_utc']):%d %b %H:%M} UTC{tag}")
                else:
                    st.caption("No official communications stored in the last 45 days (refresh news).")
    st.caption("Policy rates: FRED (Fed target, ECB deposit rate daily; BoJ call rate monthly via OECD). No current "
               "FRED series exists for Bank Rate (BoE) or the RBI repo rate — check the official pages. Communications "
               "come from each bank's official RSS feed; routine notices (auctions, operations, speeches other than the "
               "Chair's) are marked.")

with tab_add:
    st.markdown("Add RBI MPC, ECB, BoJ, BoE, China data releases, Indian CPI/GDP/IIP dates, elections, summits… "
                "**A source URL is required** so every calendar item stays verifiable.")
    with st.form("add_event", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        ev_date = f1.date_input("Date", value=date.today() + timedelta(days=1))
        ev_time = f2.text_input("Local time (optional)", placeholder="e.g. 10:00 IST")
        country = f3.selectbox("Country", ["IN", "US", "EU", "UK", "JP", "CN", "Other"])
        title = st.text_input("Event", placeholder="e.g. RBI Monetary Policy Committee decision")
        g1, g2 = st.columns([1, 3])
        importance = g1.selectbox("Importance", ["high", "medium", "low"])
        url = g2.text_input("Official source URL", placeholder="https://www.rbi.org.in/…")
        if st.form_submit_button("Add event", type="primary"):
            if not title.strip() or not url.strip().startswith("http"):
                st.error("Event title and an http(s) source URL are required.")
            else:
                with session_scope() as s:
                    s.add(EconEvent(event_date=ev_date, title=title.strip(), category="macro", importance=importance,
                                    source_url=url.strip(), country=country, event_time=ev_time.strip()))
                st.success("Added.")
                st.rerun()
    st.markdown("Official calendars: [RBI](https://www.rbi.org.in/Scripts/AnnualPolicy.aspx) · "
                "[ECB](https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html) · "
                "[BoJ](https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm) · "
                "[BoE](https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates) · "
                "[MoSPI (India CPI/GDP/IIP)](https://www.mospi.gov.in/) · "
                "[NBS China](https://www.stats.gov.cn/english/PressRelease/ReleaseCalendar/)")

with tab_ai:
    if not cal.empty:
        upcoming = cal[(cal["date"] >= date.today()) & (cal["importance"] != "low")].head(20)
        payload = {"generated_at_utc": iu.utc_now_str(), "events": [
            {**{k: (str(v) if k == "date" else v) for k, v in r.items() if k in ("date", "time_ist", "country", "event",
                                                                                 "importance", "source", "market_relevance")},
             "readings": calendars.release_readings(int(r["rid"]), r["date"]) if pd.notna(r.get("rid")) else []}
            for _, r in upcoming.iterrows()],
            "central_banks": [{k: v for k, v in cb.items() if k != "latest_communications"} for cb in calendars.central_bank_tracker()],
            "risk_appetite": iu.risk(), "note": "No consensus forecasts are available; do not invent them."}
        ui.gemini_panel("cal_ai", "Preview the week's macro risks",
                        lambda: gemini.intel_analysis("global_macro_analyst", payload, "calendar"),
                        payload_for_links=payload)

ui.disclaimer()
