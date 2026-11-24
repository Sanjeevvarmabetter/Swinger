"""Geopolitical Intelligence Centre — theaters, evidence-based event cards, market reaction, timeline, map."""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tradingos.ai import gemini
from tradingos.intel import geopolitics as geo
from tradingos.ui import charts
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=False)
iu.page_header("Geopolitical Intelligence", "What is happening, what is confirmed, why it matters for markets — "
               "evidence from stored news, framework analysis clearly labelled")

now = geo.now_naive_utc()
tagged = iu.geo_tagged()
att = geo.attention(tagged, now, since=geo.collecting_since(iu.news_raw(35)))
df, _ = iu.snapshot()

c1, c2 = st.columns([3, 1])
c1.caption(f"{len(tagged)} geopolitics-tagged items in the last 35 days across {tagged['source'].nunique() if len(tagged) else 0} "
           "sources. Theater matching is keyword-based (word boundaries) — transparent but imperfect; open the source.")
with c2:
    iu.news_refresh_button("geo_refresh")
since = geo.collecting_since(iu.news_raw(35))
if not geo.baseline_ready(since, now):
    st.info(f"Attention trends are withheld until there is a real baseline: the app compares the last 7 days with "
            f"the previous 28, and has been collecting news since {since:%d %b %Y} UTC. RSS feeds expose only a few "
            "days of history, so ratios appear after ~35 days of collection (the scheduler keeps collecting). Story "
            "counts below are real; 'Building baseline' means no trend claim is made yet." if since else
            "No news collected yet — refresh feeds.")

t_over, t_theater, t_timeline, t_map = st.tabs(["Overview", "Theater deep-dive", "Risk timeline", "Map"])

with t_over:
    show = att.sort_values("Stories 7d", ascending=False)[["Theater", "Stories 7d", "Prior weekly avg",
                                                           "Attention ratio", "Trend"]]
    a, b = st.columns([1.1, 1])
    with a:
        st.markdown("**Attention by theater (stories, last 7 days)**")
        st.dataframe(show, hide_index=True, width="stretch")
    with b:
        st.markdown("**Highest-priority geopolitical stories (7 days)**")
        top = tagged[pd.to_datetime(tagged["published_utc"]) >= now - pd.Timedelta(days=7)] if len(tagged) else tagged
        from tradingos.intel.news_rank import rank_news
        iu.story_list(rank_news(top.drop(columns=["theaters"]) if len(top) else top, now=now), n=8)

with t_theater:
    names = {t.name: t.key for t in geo.THEATERS}
    order = att.sort_values("Stories 7d", ascending=False)["Theater"].tolist()
    pick = st.selectbox("Theater", order)
    key = names[pick]
    th = geo.THEATER_BY_KEY[key]
    days = st.select_slider("Window", [3, 7, 14, 30], value=7, format_func=lambda d: f"{d} days")
    with st.container(border=True):
        st.markdown(f"**Framework — {th.name}** _(static analysis, not news)_")
        st.markdown(f"- **Typical transmission:** {th.channels}\n- **Exposed sectors:** {', '.join(th.sectors)}\n"
                    f"- **Commodities:** {', '.join(th.commodities)}\n- **Countries:** {', '.join(th.countries) or 'varies'}\n"
                    f"- **Monitor:** {th.watch}")
    st.markdown("**Market reaction — linked instruments** (is the market pricing it?)")
    mr = geo.market_reaction(df, key)
    st.dataframe(ui.color_pct_cols(mr, ["1D %", "1W %", "1M %"]), hide_index=True, width="stretch")
    cards = geo.event_cards(tagged, key, now, days=days, n=12)
    st.markdown(f"**Events ({len(cards)} story clusters, last {days} days)**")
    if not cards:
        ui.empty_state("No stored stories match this theater in the window.")
    for c in cards:
        icon, _ = iu.TIER_STYLE.get(c["tier"], ("", ""))
        with st.expander(f"{icon} {c['headline']}  ·  {c['when_utc']} UTC  ·  {c['source']}", expanded=False):
            links = " · ".join(f"[{'source' if i == 0 else f'link {i + 1}'} ↗]({u})"
                               for i, u in enumerate([c["url"], *c["other_links"]]) if u)
            st.markdown(
                f"1. **What happened:** {html.escape(c['what_happened'])}\n"
                f"2. **When:** {c['when_utc']} UTC\n"
                f"3. **Who:** {', '.join(c['who']) or 'not detected in text'}\n"
                f"4. **Confirmed:** {c['confirmed']} ({c['info_type']})"
                + (f" — also: {c['also_reported_by']}" if c['also_reported_by'] else "") + "\n"
                f"5. **Uncertain:** {c['uncertain']}\n"
                f"6. **Why it matters (framework):** {c['why_it_matters_framework']}\n"
                f"7. **Countries affected:** {', '.join(c['countries_affected']) or '—'}\n"
                f"8. **Sectors (framework):** {', '.join(c['sectors_framework'])}\n"
                f"9. **Commodities (framework):** {', '.join(c['commodities_framework']) or '—'}\n"
                f"10. **Transmission channels:** see framework above and the market-reaction table\n"
                f"11. **Monitor next (framework):** {c['monitor_next_framework']}\n\n{links}")
    payload = {"theater": th.name, "generated_at_utc": iu.utc_now_str(),
               "framework": {"channels": th.channels, "sectors": th.sectors, "commodities": th.commodities,
                             "countries": th.countries, "watch": th.watch},
               "market_reaction": mr, "events": cards[:10],
               "attention": att[att["key"] == key].drop(columns=["lat", "lon"]).to_dict("records")}
    ui.gemini_panel(f"geo_{key}", f"Analyse {th.name}",
                    lambda: gemini.intel_analysis("geopolitical_analyst", payload, th.name),
                    payload_for_links=payload)

with t_timeline:
    win = st.select_slider("Timeline window", [7, 14, 30], value=14, format_func=lambda d: f"{d} days")
    tl = geo.timeline(tagged, now, days=win)
    tl = tl[tl["tier"] != "IGNORE FOR NOW"] if len(tl) else tl
    if tl.empty:
        ui.empty_state("No geopolitical stories in the window.")
    else:
        size = {"MUST KNOW": 16, "IMPORTANT": 11, "INTERESTING": 7}
        color = {"MUST KNOW": "#EF5B67", "IMPORTANT": "#E9A23B", "INTERESTING": "#4EA8F2"}
        fig = go.Figure()
        for tier in ("INTERESTING", "IMPORTANT", "MUST KNOW"):
            d = tl[tl["tier"] == tier]
            fig.add_trace(go.Scatter(x=d["published_utc"], y=d["Theater"], mode="markers", name=tier,
                                     marker=dict(size=size[tier], color=color[tier], opacity=0.8,
                                                 line=dict(width=0.5, color="#0B0F17")),
                                     customdata=d[["headline", "source", "n_sources"]].values,
                                     hovertemplate="%{customdata[0]}<br>%{customdata[1]} · %{customdata[2]} source(s)"
                                                   "<br>%{x|%d %b %H:%M} UTC<extra></extra>"))
        fig.update_layout(title=dict(text="Geopolitical risk timeline (size/colour = priority tier)", x=0.01,
                                     font=dict(size=12)), hovermode="closest")
        fig = charts._layout(fig, max(320, 32 * tl["Theater"].nunique() + 80))
        fig.update_yaxes(side="left", showspikes=False)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(tl.sort_values("published_utc", ascending=False)[["published_utc", "Theater", "tier", "headline",
                                                                         "source", "n_sources", "url"]],
                     hide_index=True, width="stretch", height=360,
                     column_config={"url": st.column_config.LinkColumn("Source", display_text="open ↗"),
                                    "published_utc": st.column_config.DatetimeColumn("Published (UTC)", format="DD MMM HH:mm")})

with t_map:
    m = att[att["Stories 7d"] > 0]
    if m.empty:
        ui.empty_state("No active theaters in the last 7 days.")
    else:
        fig = go.Figure(go.Scattergeo(
            lat=m["lat"], lon=m["lon"], text=m["Theater"], mode="markers+text", textposition="top center",
            textfont=dict(color="#CBD5E1", size=10),
            marker=dict(size=[8 + 2.2 * v ** 0.75 for v in m["Stories 7d"]], color=m["Stories 7d"],
                        colorscale=[[0, "#1E3A5F"], [1, "#EF5B67"]], opacity=0.85, line=dict(width=0.5, color="#0B0F17"),
                        showscale=False),
            customdata=m[["Stories 7d", "Trend"]].values,
            hovertemplate="%{text}<br>%{customdata[0]} stories (7d) · %{customdata[1]}<extra></extra>"))
        fig.update_geos(projection_type="natural earth", showcountries=True, countrycolor="#1E293B",
                        showcoastlines=True, coastlinecolor="#334155", showland=True, landcolor="#0F172A",
                        showocean=True, oceancolor="#080B10", bgcolor="#080B10", showframe=False)
        fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="#080B10",
                          font=dict(color="#94A3B8"))
        st.plotly_chart(fig, width="stretch")
        st.caption("Bubble = approximate theater location, size/colour = stories in the last 7 days. Global theaters "
                   "(tariffs, sanctions, elections, military) are pinned at representative locations.")

ui.disclaimer()
