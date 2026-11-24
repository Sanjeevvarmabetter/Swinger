"""Daily Briefing — the home page: what matters today, prioritised, readable in 10–15 minutes."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from tradingos.config import load_config
from tradingos.intel import briefing as br
from tradingos.intel.instruments import UNAVAILABLE
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu
from tradingos.ui.state import refresh_market

IST = ZoneInfo("Asia/Kolkata")
AREAS = ["US Markets", "Indian Markets", "Gold & Commodities", "Geopolitics", "Economy & Central Banks",
         "Technology & AI", "Global Markets"]


def area_for(r: pd.Series) -> str:
    cat, region, topics = str(r.get("category") or ""), str(r.get("region") or ""), str(r.get("topics") or "")
    if cat == "geopolitics" or "Geopolitics" in topics:
        return "Geopolitics"
    if cat == "commodities" or "Gold & metals" in topics or "Oil & energy" in topics:
        return "Gold & Commodities"
    if region == "India" or "India markets" in topics:
        return "Indian Markets"
    if cat == "technology" or "AI & semiconductors" in topics:
        return "Technology & AI"
    if cat == "macro" or "Fed & US rates" in topics or "Inflation & growth" in topics:
        return "Economy & Central Banks"
    if region == "US" or "US equities" in topics:
        return "US Markets"
    return "Global Markets"


@st.cache_data(ttl=1800, show_spinner=False)
def _events(nonce: int) -> tuple[pd.DataFrame, list[str]]:  # noqa: ARG001
    from tradingos.intel import calendars
    return calendars.combined_events(days=3)


@st.cache_data(ttl=600, show_spinner=False)
def _x_section(nonce: int) -> dict:  # noqa: ARG001
    from tradingos.intel import xintel
    return xintel.briefing_section(max_per_list=2)


def sec_title(title: str, count: int | None = None) -> None:
    c = f'<span class="count">{count}</span>' if count is not None else ""
    st.markdown(f'<div class="sec-title">{html.escape(title)} {c}</div>', unsafe_allow_html=True)


ui.render_top_bar(show_refresh=True)
now_ist = datetime.now(timezone.utc).astimezone(IST)
ui.page_header("Daily Briefing", f"{now_ist:%A %d %B %Y} · What happened, why it matters and what to watch — "
                                 "US · India · Gold · Geopolitics · Macro · AI. Every item links to its source.")

cfg = load_config()

# ----------------------------------------------------------------------------- market strip
df, meta = iu.snapshot()
if df is None or df.empty:
    st.error(f"Market data unavailable: {meta.get('error') or 'no data returned'}. News below still works.",
             icon=":material/cloud_off:")
else:
    iu.tiles(df, ["^GSPC", "^NDX", "^NSEI", "^BSESN", "GC=F", "BZ=F", "DX-Y.NYB", "INR=X", "^TNX", "^VIX"],
             fmt={"^TNX": "{:.2f}%", "INR=X": "₹{:.2f}"})
    risk = iu.risk()
    cls = {"Risk-on": "tos-green", "Risk-off": "tos-red", "Mixed": "tos-amber"}.get(risk["label"], "")
    st.markdown(
        f'<div class="chips">{ui.chip("Risk appetite: " + risk["label"], cls)}'
        f'{ui.chip(str(risk["risk_on"]) + " risk-on · " + str(risk["risk_off"]) + " risk-off signals")}'
        f'{ui.chip("Prices retrieved " + meta["retrieved_at_utc"])}</div>', unsafe_allow_html=True)
    st.caption("Daily bars from a free delayed source — not real-time. The dot on each tile shows freshness "
               "(green current · blue delayed intraday · amber stale · red missing). Details on Global Markets.")

tab_today, tab_ai, tab_det, tab_sched = st.tabs(["Today", "AI briefing", "Facts-only edition", "Schedule & data"])

# ----------------------------------------------------------------------------- TODAY (deterministic, live)
with tab_today:
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        days = st.segmented_control("Window", [1, 2, 3], default=1, format_func=lambda d: f"Last {d * 24}h",
                                    key="brief_days", label_visibility="collapsed") or 1
        iu.news_refresh_button("brief_refresh")
    ranked = iu.ranked_news(days)   # query_news filters by publication time, so older items never appear as new
    if ranked is None or ranked.empty:
        ui.empty_state("No stories in this window yet. Use “Refresh news” to fetch the feeds.")
    else:
        ranked = ranked[ranked["tier"].isin(["MUST KNOW", "IMPORTANT", "INTERESTING"])].copy()
        ranked["area"] = ranked.apply(area_for, axis=1)
        counts = ranked["tier"].value_counts()
        st.markdown(
            '<div class="chips">' + "".join(ui.chip(f"{t.title()}: {counts.get(t, 0)}", iu.TIER_STYLE[t][1])
                                            for t in ("MUST KNOW", "IMPORTANT", "INTERESTING")) + "</div>",
            unsafe_allow_html=True)

        must = ranked[ranked["tier"] == "MUST KNOW"].head(6)
        sec_title("Must know", len(must))
        iu.story_list(must, n=6, tiers=("MUST KNOW",), empty="Nothing rated Must Know in this window.")
        shown = set(must["url"])

        for area in AREAS:
            sub = ranked[(ranked["area"] == area) & ~ranked["url"].isin(shown)]
            if sub.empty:
                continue
            top = sub.head(3)
            shown |= set(top["url"])
            sec_title(area, len(sub))
            iu.story_list(top, n=3)
            if len(sub) > 3:
                with st.expander(f"{len(sub) - 3} more in {area}"):
                    iu.story_list(sub.iloc[3:], n=20)

    # X discussions (cached only — never spends API budget from the home page)
    sec_title("Important X discussions")
    xs = _x_section(st.session_state.get("news_nonce", 0))
    if xs.get("lists"):
        cards = []
        for lst in xs["lists"]:
            for p in lst["posts"]:
                cards.append(f'<article class="xpost"><div class="who">{html.escape(p["author"])} '
                             f'<span>@{html.escape(p["handle"])} · {html.escape(lst["list"])}</span></div>'
                             f'<div class="txt">{html.escape(p["text"][:280])}</div>'
                             f'<div class="meta">{p["created_utc"]} UTC · <a href="{html.escape(p["url"], quote=True)}" '
                             f'target="_blank" rel="noopener noreferrer">Open on X ↗</a></div></article>')
        st.markdown("".join(cards), unsafe_allow_html=True)
        st.caption(xs["status"])
    else:
        ui.empty_state(xs.get("status", "X data unavailable."))

    # Upcoming catalysts
    sec_title("What to watch — next 72 hours")
    ev, ev_errs = _events(st.session_state.get("mkt_nonce", 0))
    if ev is not None and len(ev):
        ev = ev[ev["importance"].isin(["high", "medium"])] if "importance" in ev else ev
    if ev is None or ev.empty:
        ui.empty_state("No high/medium-importance scheduled releases found for the next 72 hours."
                       + (f" ({ev_errs[0]})" if ev_errs else ""))
    else:
        rows = []
        for _, r in ev.head(12).iterrows():
            imp = str(r.get("importance", ""))
            src = str(r.get("source") or "")
            link = (f' · <a href="{html.escape(src, quote=True)}" target="_blank" rel="noopener noreferrer">Source ↗</a>'
                    if src.startswith("http") else "")
            rows.append(f'<article class="story {"must" if imp == "high" else "imp"}">'
                        f'<div class="chips">{ui.chip(imp.title(), "tos-red" if imp == "high" else "tos-amber")}'
                        f'{ui.chip(str(r.get("country") or ""))}</div>'
                        f'<div class="story-head">{html.escape(str(r["event"]))}</div>'
                        f'<div class="story-meta">{pd.Timestamp(r["date"]):%a %d %b} · '
                        f'{html.escape(str(r.get("time_ist") or "time n/a"))}{link}</div></article>')
        st.markdown("".join(rows), unsafe_allow_html=True)
        st.caption("Official schedules (FRED release calendar, FOMC). Consensus forecasts are not available on the "
                   "current data plans and are never estimated. Full list on Economic Calendar.")

# ----------------------------------------------------------------------------- AI / archived editions
eds = list(br.EDITIONS.values())
default_key = br.default_edition()


def edition_controls(prefix: str):
    c1, c2 = st.columns([1.3, 1])
    ed_key = c1.selectbox("Edition", [e.key for e in eds], index=[e.key for e in eds].index(default_key),
                          format_func=lambda k: br.EDITIONS[k].title, key=f"{prefix}_ed")
    past = br.archive(limit=40, edition=ed_key)
    labels = {b.id: f"{b.edition_date:%a %d %b} · {b.created_at:%H:%M} UTC" + (" · AI" if b.ai_md else "")
              for b in past}
    pick = c2.selectbox("Issue", list(labels) or [None], format_func=lambda i: labels.get(i, "none yet"),
                        key=f"{prefix}_issue")
    return ed_key, (br.get(pick) if pick else None)


def stale_warning(b) -> None:
    age_h = (datetime.now(timezone.utc).replace(tzinfo=None) - b.created_at).total_seconds() / 3600
    if age_h > 12:
        st.warning(f"This issue was generated {age_h:.0f} hours ago — its market data and news are not current.",
                   icon=":material/schedule:")


with tab_ai:
    ed_key, b = edition_controls("ai")
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        gen_ai = st.button("Generate AI briefing", type="primary", icon=":material/auto_awesome:",
                           disabled=not cfg.ai_configured, key="gen_ai",
                           help="Refresh news + market data, build the facts-only edition and ask the AI to edit it.")
        gen_det = st.button("Facts-only edition", icon=":material/fact_check:", key="gen_det",
                            help="Same pipeline without AI — every line is sourced data or a fixed rule.")
        st.caption(f"Engine: {ui.ai_engine_label()}")
    if cfg.gemini_configured and not cfg.groq_configured:
        from tradingos.ai.gemini import FALLBACK_MODELS, quota_status
        qs = quota_status()
        if qs:
            left = [m for m in dict.fromkeys([cfg.gemini_model, *FALLBACK_MODELS]) if m not in {q["model"] for q in qs}]
            st.caption("Gemini quota: " + ", ".join(f"{q['model']} used up (resets in {q['resets_in_hours']}h)"
                                                    for q in qs)
                       + (f" · still available: {', '.join(left)}" if left else " · no models left today."))
    if gen_ai or gen_det:
        with st.spinner(f"Building {br.EDITIONS[ed_key].title}: refreshing news, markets, gold drivers and calendars"
                        + (" and asking the AI" if gen_ai else "") + "… (about a minute)"):
            refresh_market()
            nb = br.generate(ed_key, use_ai=bool(gen_ai), refresh=True)
        iu.bump_news()
        if nb.ai_error:
            ui.flash(f"Facts-only edition saved, but the AI edition failed: {nb.ai_error}", "warning")
        else:
            ui.flash("Briefing generated and archived.")
        st.rerun()
    ui.show_flash()
    if b is None:
        ui.empty_state(f"No {br.EDITIONS[ed_key].title} archived yet. Generate one above, or schedule automatic "
                       "editions (Schedule & data tab).")
    elif b.ai_md:
        stale_warning(b)
        st.caption(f"Written by {b.model} from the facts-only payload. Tags: [FACT] official · [DATA] market/economic "
                   "data · [REPORTED] media · [OPINION] analyst · [AI VIEW] interpretation · [UNVERIFIED].")
        with st.container(border=True):
            try:
                allowed = ui._payload_urls(json.loads(b.payload_json or "{}"))
            except ValueError:
                allowed = None
            ui.render_ai_markdown(b.ai_md, allowed_urls=allowed)
        st.download_button("Download (.md)", b.ai_md, file_name=f"{b.edition}-{b.edition_date}.md", key="dl_ai")
    else:
        st.info("This issue has no AI edition" + (f": {b.ai_error}" if b.ai_error else ".") +
                " The facts-only edition is complete on its own.", icon=":material/info:")

with tab_det:
    _, b2 = edition_controls("det")
    if b2 is None:
        ui.empty_state("No issue archived for this edition yet.")
    else:
        stale_warning(b2)
        with st.container(border=True):
            st.markdown(b2.deterministic_md)
        st.download_button("Download facts-only (.md)", b2.deterministic_md,
                           file_name=f"{b2.edition}-{b2.edition_date}-facts.md", key="dl_det")

with tab_sched:
    st.markdown("**Editions and schedule** (times follow US daylight saving automatically)")
    rows = [{"Edition": e.title, "Local time": f"{e.local_time:%H:%M} {e.tz.key}",
             "Days": "1st of month" if e.monthly else ", ".join("Mon Tue Wed Thu Fri Sat Sun".split()[d]
                                                                 for d in e.weekdays),
             "News window": f"{e.news_days}d"} for e in eds]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    nxt = br.next_runs()
    st.markdown("**Next runs:** " + " · ".join(f"{r['title']} — {r['at_ist']}" for r in nxt[:5]))
    st.code("*/15 * * * * cd /path/to/Swinger && .venv/bin/python scripts/intel_scheduler.py "
            ">> data/reports/scheduler.log 2>&1", language="bash")
    st.caption("Add with `crontab -e` to generate due editions automatically (each edition is made once; missed "
               "editions run within a 3-hour grace window). The computer must be awake for cron to run.")
    if df is not None and len(df):
        st.markdown("**Freshness of the current market snapshot**")
        st.markdown('<div class="chips">' + "".join(iu.fresh_chip(k) + f"&nbsp;{v}&nbsp;&nbsp;"
                                                    for k, v in df["Freshness"].value_counts().items()) + "</div>",
                    unsafe_allow_html=True)
        stale = df[~df["Freshness"].isin(["Intraday (delayed — not real-time)", "Current (latest completed session)"])]
        if len(stale):
            st.dataframe(stale[["Name", "Symbol", "Market", "Last bar", "Freshness", "Freshness note"]]
                         .drop_duplicates("Symbol"), hide_index=True, width="stretch")
    iu.unavailable_box(UNAVAILABLE)

ui.disclaimer()
