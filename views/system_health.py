"""System Health — provider permissions, data freshness, feeds and briefing pipeline."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tradingos.intel import briefing as br
from tradingos.intel import health
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=False)
iu.page_header("System Health", "What each provider actually allows on your plan, how fresh every dataset is, "
               "and whether the briefing pipeline is running")

c1, c2 = st.columns([1, 4])
force = c1.button("↻ Re-run checks")
c2.caption("Checks call one real endpoint per capability with a tiny request (cached 1 hour). Keys are never shown.")
with st.spinner("Probing providers…"):
    checks = pd.DataFrame(health.run_checks(force=force))
STATUS_COLOR = {"OK": "color:#10B981", "NOT IN PLAN": "color:#F59E0B", "NOT CONFIGURED": "color:#94A3B8",
                "ERROR": "color:#F43F5E", "RATE LIMITED": "color:#F59E0B", "EMPTY": "color:#F59E0B"}
st.dataframe(checks.style.map(lambda v: STATUS_COLOR.get(v, ""), subset=["status"]), hide_index=True, width="stretch")
st.caption("NOT IN PLAN = the key works but the subscription does not include that endpoint; the app then uses another "
           "source or shows the gap explicitly instead of estimating.")

from tradingos.ai.gemini import quota_status
qs = quota_status()
if qs:
    st.warning("Gemini models out of quota: " + ", ".join(f"{q['model']} (resets in {q['resets_in_hours']}h)" for q in qs)
               + ". Free tier ≈ 20 requests/day per model; the app skips exhausted models automatically.")

st.markdown("### Market data freshness")
df, meta = iu.snapshot()
iu.meta_line(meta)
counts = df.drop_duplicates("Symbol")["Freshness"].value_counts()
st.markdown(" ".join(iu.fresh_chip(k) + f" {v}" for k, v in counts.items()), unsafe_allow_html=True)
by_market = (df.drop_duplicates("Symbol").groupby(["Market", "Freshness"]).size().unstack(fill_value=0))
st.dataframe(by_market, width="stretch")
with st.expander("Instruments that are not current"):
    bad = df.drop_duplicates("Symbol")
    bad = bad[~bad["Freshness"].str.startswith(("Intraday", "Current"))]
    st.dataframe(bad[["Name", "Symbol", "Market", "Last bar", "Freshness", "Freshness note"]], hide_index=True,
                 width="stretch")

st.markdown("### News feeds")
fs = health.feed_status()
st.dataframe(fs, hide_index=True, width="stretch",
             column_config={"URL": st.column_config.LinkColumn("URL", display_text="feed ↗"),
                            "Newest item (UTC)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                            "Last retrieved (UTC)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
st.caption("Edit feeds in config/news_feeds.json. Items older than the news-age setting are dropped at ingestion.")

st.markdown("### Briefing pipeline")
rows = []
for ed in br.EDITIONS.values():
    last = br.latest(ed.key)
    rows.append({"Edition": ed.title, "Last issue (IST date)": last.edition_date if last else None,
                 "Created (UTC)": last.created_at if last else None,
                 "AI edition": ("yes" if last.ai_md else f"no — {last.ai_error[:60]}" if last.ai_error else "no") if last else "",
                 })
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
st.markdown("**Next scheduled:** " + " · ".join(f"{r['title']} {r['at_ist']}" for r in br.next_runs()[:4]))
st.caption("Automatic generation needs the cron line shown on the Daily Briefing page (Schedule tab).")

ui.disclaimer()
