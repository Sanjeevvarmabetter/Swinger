"""X Intelligence — posts from official, central-bank and news-desk accounts via the official X API v2."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from tradingos.intel import xintel
from tradingos.ui import components as ui

ui.render_top_bar(show_refresh=False)
ui.page_header("X Intelligence", "What central banks, officials and financial news desks are posting on X — fetched "
                                 "through the official X API. Posts are what an account said, not verified facts.")

lists = xintel.load_lists()

if not xintel.configured():
    st.info("**X is not connected.** This page reads X only through the official X API v2 (recent search), which "
            "needs a paid developer plan or pay-per-use credits. Nothing is scraped and no posts are invented.",
            icon=":material/link_off:")
    st.markdown(
        "**To enable it**\n"
        "1. Create a project and app at [developer.x.com](https://developer.x.com) and add credits or a plan that "
        "includes *recent search*.\n"
        "2. Copy the app's **Bearer token** into `.env` as `X_BEARER_TOKEN=…` (or Streamlit secrets) and restart.\n"
        "3. Optional: `X_DAILY_REQUEST_LIMIT` (default 40 requests/day) and `X_CACHE_MINUTES` (default 30) cap spend.")
    if lists:
        st.markdown('<div class="sec-title">Watch lists that will be queried</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"List": i["title"], "X search query": i["query"]} for i in lists]),
                     hide_index=True, width="stretch")
        st.caption("Edit config/x_sources.json to change the accounts and keywords.")
    st.stop()

if not lists:
    ui.empty_state("No watch lists in config/x_sources.json.")
    st.stop()

used, limit = xintel.budget_used(), xintel.daily_limit()
st.markdown(" ".join([ui.chip(f"API requests today: {used}/{limit}", "tos-amber" if used >= limit else ""),
                      ui.chip(f"Cache: {xintel.cache_minutes()} min")]), unsafe_allow_html=True)

titles = [i["title"] for i in lists]
pick = st.segmented_control("List", titles, default=titles[0], key="x_list", label_visibility="collapsed") or titles[0]
item = next(i for i in lists if i["title"] == pick)
c1, c2 = st.columns([1, 1])
sort = c1.selectbox("Sort", ["Newest", "Most engagement"], key="x_sort")
force = c2.button("Fetch latest", icon=":material/refresh:", help="Spends one API request (otherwise cached).")

with st.spinner("Fetching from X…"):
    res = xintel.fetch_list(item, force=force)

if res.error:
    (st.warning if res.posts else st.error)(res.error, icon=":material/error:")
if res.fetched_at_utc:
    st.caption(f"Fetched {res.fetched_at_utc}" + (" (cached)" if res.from_cache else "") + f" · query: `{item['query']}`")
posts = res.posts
if sort == "Most engagement":
    posts = sorted(posts, key=lambda p: p["likes"] + 2 * p["reposts"] + p["replies"], reverse=True)
if not posts and not res.error:
    ui.empty_state("No posts matched this list in the last 7 days (X recent search window).")
cards = []
for p in posts:
    badge = " ✓" if p["verified"] else ""
    cards.append(
        f'<article class="xpost"><div class="who">{html.escape(p["author"])}{badge} <span>@{html.escape(p["handle"])}</span></div>'
        f'<div class="txt">{html.escape(p["text"])}</div>'
        f'<div class="meta">{p["created_utc"]} UTC · ♥ {p["likes"]:,} · ↻ {p["reposts"]:,} · 💬 {p["replies"]:,} · '
        f'<a href="{html.escape(p["url"], quote=True)}" target="_blank" rel="noopener noreferrer">Open on X ↗</a></div></article>')
st.markdown("".join(cards), unsafe_allow_html=True)
