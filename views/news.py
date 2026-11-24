"""News Intelligence — ranked, de-duplicated, entity-tagged news with story threads and source statistics."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from tradingos import watchlist
from tradingos.ai import gemini
from tradingos.config import load_config
from tradingos.data.news import load_feed_config, refresh_news
from tradingos.intel import entities
from tradingos.intel.news_rank import SCORING_RULES, TIERS, rank_news, threads
from tradingos.journal.service import trades_dataframe
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=False)
iu.page_header("News Intelligence", "Ranked, de-duplicated and source-attributed headlines · story threads · entities · "
               "factual vs speculative tagging. Headlines + short feed summaries only; full articles stay with publishers.")

cfg = ui.settings()

with st.expander("Feeds, ticker news & data sources", expanded=False):
    st.dataframe(pd.DataFrame(load_feed_config())[["name", "region", "category", "official", "url"]], hide_index=True,
                 width="stretch", column_config={"url": st.column_config.LinkColumn("URL", display_text="feed ↗")})
    st.caption("Also ingested: Finnhub general & forex news (free tier). Feed health is on the System Health page.")
    if not load_config().sec_user_agent:
        st.info("SEC EDGAR filings require SEC_USER_AGENT configured in .env.")
    wl = [w.ticker for w in watchlist.items()]
    open_t = trades_dataframe("OPEN")
    op = list(open_t["ticker"].unique()) if len(open_t) else []
    extra = st.text_input("Ticker news for (watchlist & open positions)", ",".join(dict.fromkeys(wl + op)))
    if st.button("↻ Fetch feeds + ticker news", type="primary"):
        tick = [t.strip().upper() for t in extra.split(",") if t.strip()][:25]
        with st.spinner("Ingesting RSS feeds, Finnhub and company news…"):
            status = refresh_news(tick, max_age_days=max(cfg.news_max_age_days, 35))
        iu.bump_news()
        st.toast(f"Fetched {status['fetched']} · {status['stored']} new · {status['duplicates']} duplicates skipped · "
                 f"{len(status['errors'])} errors")
        for e in status["errors"][:5]:
            st.warning(e)

# ----------------------------------------------------------------------------- filters
f = st.columns([1, 1, 1, 1, 1.2])
days = f[0].selectbox("Window", [1, 2, 3, 7, 14, 30], index=3, format_func=lambda d: f"Last {d}d")
region = f[1].selectbox("Region", ["All", "US", "India", "Global", "Asia", "Europe"])
cat = f[2].selectbox("Category", ["All", "macro", "geopolitics", "technology", "earnings", "commodities", "markets",
                                  "regulation", "company"])
tiers = f[3].multiselect("Tier", [t for _, t in TIERS], default=["MUST KNOW", "IMPORTANT", "INTERESTING"])
query = f[4].text_input("Search / symbol", placeholder="e.g. tariff, RBI, NVDA").strip()
g = st.columns([1.3, 1, 1])
info = g[0].selectbox("Information veracity", ["All", "Confirmed (official source)", "Reported (news media)",
                                               "Analyst interpretation / opinion", "Speculation / unconfirmed"])
sent = g[1].selectbox("Sentiment (keyword heuristic)", ["All", "positive", "negative", "neutral"])
min_src = g[2].selectbox("Min. independent sources", [1, 2, 3], format_func=lambda n: f"≥ {n}")

raw = iu.news_raw(35)
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

t_feed, t_threads, t_ent, t_src, t_ai = st.tabs(["Ranked feed", "Story threads", "Entities & trends", "Sources & dedupe",
                                                 "AI synthesis"])

with t_feed:
    st.caption(f"{len(df)} stored items in the filter → {len(ranked)} distinct stories after clustering near-duplicates.")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed")
    if ranked.empty:
        ui.empty_state("No stories match. Broaden filters or refresh feeds.")
    elif view == "Cards":
        iu.story_list(ranked, n=60, tiers=tuple(tiers) or tuple(t for _, t in TIERS))
    else:
        st.dataframe(ranked[["tier", "score", "published_utc", "headline", "source", "n_sources", "region", "category",
                             "info_type", "topics", "also_reported_by", "url"]], hide_index=True, width="stretch",
                     height=560, column_config={
                         "url": st.column_config.LinkColumn("Source", display_text="open ↗"),
                         "published_utc": st.column_config.DatetimeColumn("Published (UTC)", format="DD MMM HH:mm")})
    with st.expander("Ranking rules (deterministic)"):
        st.table(pd.DataFrame(SCORING_RULES, columns=["Rule", "Points"]))
        st.caption("Tiers: " + " · ".join(f"{label} ≥ {cut}" for cut, label in TIERS[:-1]) + " · else IGNORE FOR NOW.")

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
                            lambda r=r: gemini.intel_analysis("news_summary", {"thread": r.to_dict()}, "thread"))

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
        for col, title, a, b in zip(cols, ["Countries & regions", "Institutions", "Tickers"], cur, prv):
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
    ui.gemini_panel("news_impact", "Generate AI market-impact synthesis",
                    lambda: gemini.news_impact({"headlines": top, "note": "Classify confirmed facts vs speculation; "
                                                                          "cite source and time for each item."}),
                    help_text="Probable sector effects and what is confirmed vs speculative, for the filtered stories.")

ui.disclaimer()
