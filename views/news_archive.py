"""News Archive — every stored headline, searchable and ranked, plus the archive of past briefings."""
from __future__ import annotations

import json
from collections import Counter

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.config import load_config
from tradingos.data.news import load_feed_config, refresh_news
from tradingos.intel import briefing as br
from tradingos.intel import entities
from tradingos.intel.news_rank import SCORING_RULES, TIERS, rank_news, threads
from tradingos.settings import load_settings
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=False)
iu.page_header("News Archive", "Every stored headline — ranked, de-duplicated and source-attributed — plus past "
               "briefings. Headlines and short feed summaries only; full articles stay with the publishers.")

cfg = load_settings()

# ----------------------------------------------------------------------------- search + filters
c1, c2 = st.columns([2, 1])
query = c1.text_input("Search headlines, summaries or a ticker", placeholder="e.g. tariff, RBI, NVDA, gold",
                      key="arch_q").strip()
days = c2.selectbox("Window", [1, 2, 3, 7, 14, 30, 90, 365], index=3, format_func=lambda d: f"Last {d} days",
                    key="arch_days")
with st.expander("More filters", icon=":material/filter_list:"):
    f = st.columns(3)
    region = f[0].selectbox("Region", ["All", "US", "India", "Global", "Asia", "Europe"])
    cat = f[1].selectbox("Category", ["All", "macro", "geopolitics", "technology", "earnings", "commodities", "markets",
                                      "regulation", "company"])
    tiers = f[2].multiselect("Importance", [t for _, t in TIERS], default=["MUST KNOW", "IMPORTANT", "INTERESTING"])
    g = st.columns(3)
    info = g[0].selectbox("Verification", ["All", "Confirmed (official source)", "Reported (news media)",
                                           "Analyst interpretation / opinion", "Speculation / unconfirmed"])
    sent = g[1].selectbox("Tone (keyword heuristic)", ["All", "positive", "negative", "neutral"])
    min_src = g[2].selectbox("Independent sources", [1, 2, 3], format_func=lambda n: f"≥ {n}")
with st.expander("Feeds & fetching", icon=":material/rss_feed:"):
    st.dataframe(pd.DataFrame(load_feed_config())[["name", "region", "category", "official", "url"]], hide_index=True,
                 width="stretch", column_config={"url": st.column_config.LinkColumn("URL", display_text="feed ↗")})
    st.caption("Also ingested: Finnhub general & forex news (free tier). Feed health is on the System Health page.")
    if not load_config().sec_user_agent:
        st.caption("SEC EDGAR filings need SEC_USER_AGENT in .env.")
    extra = st.text_input("Also fetch company news for tickers (comma-separated, optional)", "", key="arch_tickers")
    if st.button("Fetch feeds now", type="primary", icon=":material/refresh:"):
        tick = [t.strip().upper() for t in extra.split(",") if t.strip()][:25]
        with st.spinner("Ingesting RSS feeds, Finnhub and company news…"):
            status = refresh_news(tick, max_age_days=max(cfg.news_max_age_days, 35))
        iu.bump_news()
        st.toast(f"Fetched {status['fetched']} · {status['stored']} new · {status['duplicates']} duplicates skipped · "
                 f"{len(status['errors'])} errors")
        for e in status["errors"][:5]:
            st.warning(e)

raw = iu.news_raw(max(35, days * 2))
now = pd.Timestamp(iu.utc_now_str()[:16])
df = raw[pd.to_datetime(raw["published_utc"]) >= now - pd.Timedelta(days=days)] if len(raw) else raw
if len(df):
    if region != "All":
        df = df[df["region"] == region]
    if cat != "All":
        df = df[df["category"] == cat]
    if info != "All":
        df = df[df["info_type"] == info]
    if sent != "All":
        df = df[df["sentiment"] == sent]
    if query:
        q = query.lower()
        df = df[df["headline"].str.lower().str.contains(q, regex=False) | df["summary"].str.lower().str.contains(q, regex=False)
                | df["tickers"].str.upper().str.split(",").map(lambda x: query.upper() in x)]

ranked = rank_news(df, now=now.to_pydatetime()) if len(df) else rank_news(pd.DataFrame())
if len(ranked):
    ranked = ranked[ranked["tier"].isin(tiers) & (ranked["n_sources"] >= min_src)]

t_feed, t_brief, t_threads, t_ent, t_src, t_ai = st.tabs(["Stories", "Past briefings", "Story threads", "Entities",
                                                          "Sources", "AI synthesis"])

with t_feed:
    st.caption(f"{len(df)} stored items in the filter → {len(ranked)} distinct stories after clustering near-duplicates.")
    view = st.segmented_control("View", ["Cards", "Table"], default="Cards", label_visibility="collapsed",
                                key="arch_view") or "Cards"
    if ranked.empty:
        ui.empty_state("No stories match. Broaden the window or filters, or fetch feeds.")
    elif view == "Cards":
        shown = st.session_state.get("arch_n", 30)
        iu.story_list(ranked, n=shown, tiers=tuple(tiers) or tuple(t for _, t in TIERS))
        if len(ranked) > shown and st.button(f"Show more ({len(ranked) - shown} remaining)", key="arch_more"):
            st.session_state["arch_n"] = shown + 30
            st.rerun()
    else:
        st.dataframe(ranked[["tier", "score", "published_utc", "headline", "source", "n_sources", "region", "category",
                             "info_type", "topics", "also_reported_by", "url"]], hide_index=True, width="stretch",
                     height=560, column_config={
                         "url": st.column_config.LinkColumn("Source", display_text="open ↗"),
                         "published_utc": st.column_config.DatetimeColumn("Published (UTC)", format="DD MMM HH:mm")})
    with st.expander("Ranking rules (deterministic)"):
        st.table(pd.DataFrame(SCORING_RULES, columns=["Rule", "Points"]))
        st.caption("Tiers: " + " · ".join(f"{label} ≥ {cut}" for cut, label in TIERS[:-1]) + " · else IGNORE FOR NOW.")

with t_brief:
    eds = {k: e.title for k, e in br.EDITIONS.items()}
    pick_ed = st.selectbox("Edition", ["All", *eds], format_func=lambda k: "All editions" if k == "All" else eds[k],
                           key="arch_ed")
    past = br.archive(limit=120, edition=None if pick_ed == "All" else pick_ed)
    if not past:
        ui.empty_state("No briefings archived yet. Generate one from the Daily Briefing page.")
    for b in past:
        with st.expander(f"{eds.get(b.edition, b.edition)} · {b.edition_date:%a %d %b %Y} · "
                         f"{b.created_at:%H:%M} UTC" + (" · AI edition" if b.ai_md else " · facts only")):
            md = b.ai_md or b.deterministic_md
            if b.ai_md:
                ui.render_ai_markdown(md, allowed_urls=ui._payload_urls(json.loads(b.payload_json or "{}")))
            else:
                st.markdown(md)
            st.download_button("Download (.md)", md, file_name=f"{b.edition}-{b.edition_date}.md", key=f"dl_{b.id}")

with t_threads:
    st.caption("Developing stories: clusters with at least two stored reports, ordered by number of independent "
               "sources. Use them to see how a story evolved and which outlets confirmed it.")
    th = threads(df, now=now.to_pydatetime()) if len(df) else threads(pd.DataFrame())
    if th.empty:
        ui.empty_state("No multi-report threads in this window.")
    for i, r in th.head(25).iterrows():
        icon = iu.TIER_STYLE.get(r["tier"], ("", ""))[0]
        with st.expander(f"{icon} {r['headline']}  ·  {r['n_sources']} sources · {r['n_items']} reports · "
                         f"{r['first_seen']:%d %b %H:%M} → {r['last_seen']:%d %b %H:%M} UTC"):
            st.caption(f"Region {r['region']} · topics {r['topics'] or '—'} · span {r['span_hours']}h")
            for x in r["timeline"]:
                st.markdown(f"- `{x['published_utc']}` **{x['source']}** — [{x['headline']}]({x['url']})")
            ui.gemini_panel(f"thread_{i}", "Summarise this thread",
                            lambda r=r: gemini.intel_analysis("news_summary", {"thread": r.to_dict()}, "thread"),
                            payload_for_links={"thread": r.to_dict()})

with t_ent:
    if df.empty:
        ui.empty_state("No items.")
    else:
        prev_raw = raw[(pd.to_datetime(raw["published_utc"]) < now - pd.Timedelta(days=days)) &
                       (pd.to_datetime(raw["published_utc"]) >= now - pd.Timedelta(days=2 * days))] if len(raw) else raw

        def count(frame: pd.DataFrame) -> tuple[Counter, Counter, Counter]:
            c, i, t = Counter(), Counter(), Counter()
            for h, s, tk in zip(frame["headline"], frame["summary"], frame["tickers"]):
                e = entities.extract(f"{h} {s or ''}")
                c.update(e["countries"])
                i.update(e["institutions"])
                t.update(x for x in str(tk).split(",") if x)
            return c, i, t

        cur, prv = count(df), count(prev_raw) if len(prev_raw) else (Counter(), Counter(), Counter())
        cols = st.columns(3)
        for col, title, a, b in zip(cols, ["Countries & regions", "Institutions", "Tickers"], cur, prv):  # noqa: B007
            rows = [{"Entity": k, "Mentions": v, "Previous window": b.get(k, 0), "Change": v - b.get(k, 0)}
                    for k, v in a.most_common(15)]
            col.markdown(f"**{title}**")
            col.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"Mentions in the selected {days}-day window vs the {days} days before it. Gazetteer-based "
                   "extraction (word-boundary) — explainable, but it only finds listed entities.")

with t_src:
    if raw.empty:
        ui.empty_state("No items stored.")
    else:
        w = raw[pd.to_datetime(raw["published_utc"]) >= now - pd.Timedelta(days=days)]
        rk = rank_news(w, now=now.to_pydatetime())
        st.metric("Stored items → distinct stories", f"{len(w)} → {len(rk)}",
                  help="Difference = near-duplicate reports merged into clusters (still counted as corroboration).")
        src = w.groupby("source").agg(items=("headline", "size"), newest=("published_utc", "max"),
                                      official=("info_type", lambda s: (s.str.startswith("Confirmed")).mean() > 0.5)) \
               .sort_values("items", ascending=False).reset_index()
        st.dataframe(src, hide_index=True, width="stretch",
                     column_config={"newest": st.column_config.DatetimeColumn("Newest (UTC)", format="DD MMM HH:mm")})

with t_ai:
    top = ranked.head(25)[["tier", "published_utc", "headline", "source", "url", "tickers", "category", "region",
                           "info_type", "n_sources"]] if len(ranked) else []
    ui.gemini_panel("news_impact", "AI market-impact synthesis",
                    lambda: gemini.news_impact({"headlines": top, "note": "Classify confirmed facts vs speculation; "
                                                                          "cite source and time for each item."}),
                    help_text="Probable sector effects and what is confirmed vs speculative, for the filtered stories.",
                    payload_for_links={"headlines": top.to_dict("records") if len(ranked) else []})

ui.disclaimer()
