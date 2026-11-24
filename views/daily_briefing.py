"""Daily Briefing — the intelligence command centre (default landing page)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from tradingos.config import load_config
from tradingos.intel import briefing as br
from tradingos.intel.instruments import UNAVAILABLE
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu
from tradingos.ui.state import refresh_market

ui.render_top_bar(show_refresh=True)
iu.page_header("Daily Intelligence Briefing",
               "What happened, why it matters, what to watch — US · India · Gold · Geopolitics · AI. "
               "Facts are sourced and timestamped; AI interpretation is labelled.")

cfg = load_config()
eds = list(br.EDITIONS.values())
default_key = br.default_edition()

# ----------------------------------------------------------------------------- market strip
df, meta = iu.snapshot()
iu.tiles(df, ["^GSPC", "^NDX", "^NSEI", "^BSESN", "GC=F"], per_row=5)
iu.tiles(df, ["BZ=F", "DX-Y.NYB", "INR=X", "^TNX", "^VIX"], per_row=5, fmt={"^TNX": "{:.2f}%"})
risk = iu.risk()
cls = {"Risk-on": "tos-green", "Risk-off": "tos-red", "Mixed": "tos-amber"}.get(risk["label"], "")
st.markdown(
    f'{ui.chip("Cross-asset risk appetite: " + risk["label"], cls)} '
    f'{ui.chip(str(risk["risk_on"]) + " risk-on / " + str(risk["risk_off"]) + " risk-off signals")} '
    f'{ui.chip("Market data retrieved " + meta["retrieved_at_utc"])}',
    unsafe_allow_html=True)
st.caption("Tiles show the latest daily bar from a free delayed source — never real-time. Badge = exchange-aware "
           "freshness (e.g. 'Stale' on an exchange holiday). Full checklist on Global Markets.")

# ----------------------------------------------------------------------------- edition controls
c1, c2, c3, c4 = st.columns([2.2, 1.6, 1.2, 1.2])
ed_key = c1.selectbox("Edition", [e.key for e in eds], index=[e.key for e in eds].index(default_key),
                      format_func=lambda k: br.EDITIONS[k].title)
past = br.archive(limit=40, edition=ed_key)
labels = {b.id: f"{b.edition_date:%a %d %b} · created {b.created_at:%H:%M} UTC" + (" · AI" if b.ai_md else "")
          for b in past}
pick = c2.selectbox("Issue", list(labels) or [None], format_func=lambda i: labels.get(i, "none yet"))
with c3:
    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
    gen_ai = st.button("✨ Generate now", type="primary", width="stretch", disabled=not cfg.gemini_configured,
                       help="Refresh news + market data, build the deterministic edition and ask Gemini to edit it.")
with c4:
    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
    gen_det = st.button("Facts-only edition", width="stretch",
                        help="Same pipeline without Gemini — every line is sourced data or a fixed rule.")

if cfg.gemini_configured:
    from tradingos.ai.gemini import FALLBACK_MODELS, quota_status
    qs = quota_status()
    if qs:
        left = [m for m in dict.fromkeys([cfg.gemini_model, *FALLBACK_MODELS]) if m not in {q["model"] for q in qs}]
        st.caption("Gemini quota: " + ", ".join(f"{q['model']} used up (resets in {q['resets_in_hours']}h)" for q in qs)
                   + (f" · still available: {', '.join(left)}" if left else " · no models left today — facts-only "
                      "edition only. Free tier ≈ 20 requests/day per model; enabling billing raises it."))

if gen_ai or gen_det:
    with st.spinner(f"Building {br.EDITIONS[ed_key].title}: refreshing news, markets, gold drivers, calendars"
                    + (" and asking Gemini" if gen_ai else "") + "…"):
        refresh_market()
        b = br.generate(ed_key, use_ai=bool(gen_ai), refresh=True)
    iu.bump_news()
    if b.ai_error:
        ui.flash(f"Deterministic edition saved; AI edition failed: {b.ai_error}", "warning")
    else:
        ui.flash("Briefing generated and archived.")
    st.rerun()
ui.show_flash()

b = br.get(pick) if pick else None
if b is None:
    st.info(f"No **{br.EDITIONS[ed_key].title}** archived yet. Click **Generate now** (or *Facts-only*), or schedule "
            "automatic editions — see *Schedule* below. Today's ranked stories are shown meanwhile.")
else:
    age_h = (datetime.now(timezone.utc).replace(tzinfo=None) - b.created_at).total_seconds() / 3600
    if age_h > 12:
        st.warning(f"This issue was generated {age_h:.0f} hours ago — market data and news in it are not current.")

tab_ai, tab_det, tab_stories, tab_sched = st.tabs(["Briefing (AI-edited)", "Facts-only edition", "Ranked stories (live)",
                                                   "Schedule & data quality"])
with tab_ai:
    if b is None:
        ui.empty_state("No issue selected.")
    elif b.ai_md:
        st.caption(f"Edited by Gemini ({b.model}) from the facts-only payload. Tags: [FACT] official · [DATA] market/"
                   "economic data · [REPORTED] media · [OPINION] analyst · [AI VIEW] interpretation · [UNVERIFIED].")
        with st.container(border=True):
            st.markdown(b.ai_md)
        st.download_button("Download (.md)", b.ai_md, file_name=f"{b.edition}-{b.edition_date}.md")
    else:
        st.info("This issue has no AI edition" + (f": {b.ai_error}" if b.ai_error else ".") +
                " The facts-only edition is complete on its own.")

with tab_det:
    if b is None:
        ui.empty_state("No issue selected.")
    else:
        with st.container(border=True):
            st.markdown(b.deterministic_md)
        st.download_button("Download facts-only (.md)", b.deterministic_md,
                           file_name=f"{b.edition}-{b.edition_date}-facts.md")
        with st.expander("Raw payload sent to Gemini (audit)"):
            try:
                st.json(json.loads(b.payload_json), expanded=False)
            except Exception:
                st.code(b.payload_json[:5000])

with tab_stories:
    f1, f2, f3 = st.columns([1, 1, 2])
    days = f1.selectbox("Window", [1, 2, 3, 7], index=1, format_func=lambda d: f"Last {d}d")
    region = f2.selectbox("Region", ["All", "US", "India", "Global", "Asia", "Europe"])
    if f3.button("↻ Refresh news feeds"):
        from tradingos.data.news import refresh_news
        with st.spinner("Fetching RSS, Finnhub and official feeds…"):
            s = refresh_news([], max_age_days=35)
        iu.bump_news()
        st.toast(f"{s['stored']} new · {s['duplicates']} duplicates · {s['stale']} stale dropped · {len(s['errors'])} errors")
    ranked = iu.ranked_news(days, None if region == "All" else region)
    if len(ranked):
        counts = ranked["tier"].value_counts()
        st.markdown(" ".join(ui.chip(f"{iu.TIER_STYLE[t][0]} {t}: {counts.get(t, 0)}", iu.TIER_STYLE[t][1])
                             for t in iu.TIER_STYLE), unsafe_allow_html=True)
    for tier in ("MUST KNOW", "IMPORTANT", "INTERESTING"):
        sub = ranked[ranked["tier"] == tier] if len(ranked) else ranked
        with st.expander(f"{iu.TIER_STYLE[tier][0]} {tier} ({len(sub)})", expanded=tier != "INTERESTING"):
            iu.story_list(sub, n=25, tiers=(tier,), empty="Nothing in this tier.")
    with st.expander("How stories are ranked (deterministic)"):
        from tradingos.intel.news_rank import SCORING_RULES, TIERS
        st.table(pd.DataFrame(SCORING_RULES, columns=["Rule", "Points"]))
        st.caption("Tiers: " + " · ".join(f"{label} ≥ {cut}" for cut, label in TIERS[:-1]) +
                   " · otherwise IGNORE FOR NOW. Near-duplicate headlines are clustered; the official or earliest "
                   "report is shown and other outlets are listed as corroboration.")

with tab_sched:
    st.markdown("**Editions and schedule** (times convert automatically for US daylight saving)")
    rows = [{"Edition": e.title, "Local time": f"{e.local_time:%H:%M} {e.tz.key}",
             "Days": "1st of month" if e.monthly else ", ".join("Mon Tue Wed Thu Fri Sat Sun".split()[d] for d in e.weekdays),
             "News window": f"{e.news_days}d"} for e in eds]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    nxt = br.next_runs()
    st.markdown("**Next runs:** " + " · ".join(f"{r['title']} — {r['at_ist']}" for r in nxt[:5]))
    st.code("# Generate due editions automatically (run every 15 minutes; safe to re-run — each edition is made once):\n"
            "*/15 * * * * cd /Users/sanjeevvarma/projects/Swinger && .venv/bin/python scripts/intel_scheduler.py "
            ">> data/reports/scheduler.log 2>&1", language="bash")
    st.caption("Add with `crontab -e`. Your Mac must be awake for cron to run; missed editions are generated within a "
               "3-hour grace window, otherwise use Generate now.")
    st.markdown("**Data quality of the current market snapshot**")
    st.markdown(" ".join(iu.fresh_chip(k) + f" {v}" for k, v in df["Freshness"].value_counts().items()),
                unsafe_allow_html=True)
    stale = df[~df["Freshness"].isin(["Intraday (delayed — not real-time)", "Current (latest completed session)"])]
    if len(stale):
        st.dataframe(stale[["Name", "Symbol", "Market", "Last bar", "Freshness", "Freshness note"]].drop_duplicates("Symbol"),
                     hide_index=True, width="stretch")
    iu.unavailable_box(UNAVAILABLE)
    st.caption("X/Twitter intelligence, live newsroom, geopolitics centre and trends radar arrive in later stages; "
               "briefings say so explicitly instead of filling the gap.")

ui.disclaimer()
