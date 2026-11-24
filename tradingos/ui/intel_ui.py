"""Shared Streamlit helpers for the intelligence pages (cached data access + compact renderers)."""
from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tradingos.data.base import Freshness
from tradingos.ui import charts
from tradingos.ui import components as ui

FRESH_CHIP = {
    Freshness.INTRADAY_DELAYED.value: ("Delayed intraday", "tos-blue"),
    Freshness.CURRENT.value: ("Current", "tos-green"),
    Freshness.STALE.value: ("Stale", "tos-amber"),
    Freshness.VERY_STALE.value: ("Very stale", "tos-red"),
    Freshness.MISSING.value: ("Missing", "tos-red"),
}
PCT_COLS = ["1D %", "1W %", "1M %", "3M %", "YTD %", "1Y %"]


def _nonce() -> int:
    return st.session_state.get("mkt_nonce", 0)


@st.cache_data(ttl=900, show_spinner=False)
def _snapshot(nonce: int):  # noqa: ARG001
    from tradingos.intel import markets
    return markets.snapshot()


def snapshot() -> tuple[pd.DataFrame, dict]:
    return _snapshot(_nonce())


@st.cache_data(ttl=900, show_spinner=False)
def _closes(nonce: int) -> dict[str, pd.Series]:  # noqa: ARG001
    from tradingos.intel import markets
    res = markets.load_histories()
    return {s: f["Close"].dropna() for s, f in (res.data or {}).items()}


def closes() -> dict[str, pd.Series]:
    return _closes(_nonce())


@st.cache_data(ttl=900, show_spinner=False)
def _risk(nonce: int) -> dict:  # noqa: ARG001
    from tradingos.data.macro import MACRO_SERIES, get_series
    from tradingos.intel import markets
    df, _ = snapshot()
    hy = next(m for m in MACRO_SERIES if m.sid == "BAMLH0A0HYM2")
    r = get_series(hy)
    return markets.risk_appetite(df, float(r.data.iloc[-1]) if r.ok and len(r.data) else None)


def risk() -> dict:
    return _risk(_nonce())


@st.cache_data(ttl=900, show_spinner=False)
def _ranked_news(days: int, region: str | None, nonce: int) -> pd.DataFrame:  # noqa: ARG001
    from tradingos.data.news import query_news
    from tradingos.intel.news_rank import rank_news
    return rank_news(query_news(days=days, region=region, limit=800))


def ranked_news(days: int = 2, region: str | None = None) -> pd.DataFrame:
    return _ranked_news(days, region, _nonce() + st.session_state.get("news_nonce", 0))


def bump_news() -> None:
    st.session_state["news_nonce"] = st.session_state.get("news_nonce", 0) + 1


# ----------------------------------------------------------------------------- renderers
def fresh_chip(freshness: str) -> str:
    label, cls = FRESH_CHIP.get(freshness, (freshness or "?", ""))
    return ui.chip(label, cls)


def meta_line(meta: dict) -> None:
    parts = [ui.chip(f"Source: {meta.get('source', '?')}"), ui.chip(f"Retrieved {meta.get('retrieved_at_utc', '?')}")]
    if meta.get("missing"):
        parts.append(ui.chip(f"Missing: {', '.join(meta['missing'][:8])}", "tos-amber"))
    if meta.get("error"):
        parts.append(ui.chip(f"Error: {str(meta['error'])[:80]}", "tos-red"))
    st.markdown(" ".join(parts), unsafe_allow_html=True)
    if meta.get("note"):
        st.caption(meta["note"])


def tiles(df: pd.DataFrame, symbols: list[str], per_row: int = 5, fmt: dict[str, str] | None = None) -> None:
    """Compact metric cards with 1D change, last-bar date and freshness. Skips nothing silently: missing → 'n/a'."""
    from tradingos.intel.markets import row
    fmt = fmt or {}
    cards = []
    for sym in symbols:
        r = row(df, sym)
        if r is None:
            name = df.loc[df["Symbol"] == sym, "Name"]
            cards.append(ui.terminal_metric_card(name.iloc[0] if len(name) else sym, "n/a", sub="no data returned",
                                                 badge_label="Missing", badge_color="red"))
            continue
        val = fmt.get(sym, "{:,.2f}").format(r["Last"])
        label, _ = FRESH_CHIP.get(r["Freshness"], ("?", ""))
        color = {"Current": "green", "Delayed intraday": "blue", "Stale": "amber"}.get(label, "red")
        inverse = sym in ("^VIX", "^INDIAVIX", "^MOVE")
        cards.append(ui.terminal_metric_card(r["Name"], val, delta=ui.pct(r["1D %"], 2), delta_pct=r["1D %"],
                                             sub=f"1W {ui.pct(r['1W %'])} · 1M {ui.pct(r['1M %'])} · bar {r['Last bar']}",
                                             sparkline_vals=r["sparkline"], inverse=inverse,
                                             badge_label=label, badge_color=color))
    for i in range(0, len(cards), per_row):
        cols = st.columns(per_row)
        for c, card in zip(cols, cards[i:i + per_row]):
            c.markdown(card, unsafe_allow_html=True)


def perf_table(df: pd.DataFrame, height: int | None = None, show_group: bool = False) -> None:
    if df is None or df.empty:
        ui.empty_state("No data for this group.")
        return
    cols = (["Group"] if show_group else []) + ["Name", "Symbol", "Last", *PCT_COLS, "sparkline", "Last bar",
                                                "Freshness", "Freshness note"]
    d = df[[c for c in cols if c in df.columns]].copy()
    st.dataframe(
        d, hide_index=True, width="stretch", **({"height": height} if height else {}),
        column_config={
            "Last": st.column_config.NumberColumn(format="%.2f"),
            **{c: st.column_config.NumberColumn(c, format="%+.2f") for c in PCT_COLS},
            "sparkline": st.column_config.LineChartColumn("30d", width="small"),
            "Freshness note": st.column_config.TextColumn("Freshness note", width="medium"),
        },
    )


def heatmap(df: pd.DataFrame, cols: list[str] | None = None, title: str = "", height: int | None = None) -> go.Figure:
    """Instrument × period % change heat grid (diverging, zero-centred)."""
    cols = cols or ["1D %", "1W %", "1M %", "3M %", "YTD %"]
    d = df.dropna(subset=["Last"]).set_index("Name")[cols].astype(float)
    if d.empty:
        return charts._layout(go.Figure(), 200)
    z = d.values
    lim = max(1.0, float(pd.Series(abs(z.ravel())).quantile(0.9)))
    fig = go.Figure(go.Heatmap(
        z=z, x=cols, y=d.index, zmid=0, zmin=-lim, zmax=lim,
        colorscale=[[0, "#B91C1C"], [0.5, "#111827"], [1, "#047857"]],
        text=[[("—" if pd.isna(v) else f"{v:+.1f}") for v in rowv] for rowv in z], texttemplate="%{text}",
        textfont=dict(family="JetBrains Mono, monospace", size=11), showscale=False,
        hovertemplate="%{y} · %{x}: %{z:+.2f}%<extra></extra>"))
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=12)), hovermode="closest")
    fig = charts._layout(fig, height or max(220, 26 * len(d) + 60))
    fig.update_yaxes(autorange="reversed", side="left", showspikes=False)
    fig.update_xaxes(side="top", showspikes=False)
    return fig


def rebased_chart(closes_: dict[str, pd.Series], names: dict[str, str], days: int = 180, title: str = "") -> go.Figure:
    series = {}
    for sym, name in names.items():
        s = closes_.get(sym)
        if s is None or len(s) < 5:
            continue
        s = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
        series[name] = (s / s.iloc[0] - 1) * 100
    fig = go.Figure()
    palette = ["#38BDF8", "#10B981", "#F59E0B", "#A855F7", "#F43F5E", "#E2E8F0", "#22D3EE", "#FB923C"]
    for i, (n, s) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=n, line=dict(width=1.6, color=palette[i % len(palette)])))
    fig.add_hline(y=0, line=dict(color="#334155", dash="dot"))
    fig.update_layout(title=dict(text=title or f"Performance, last {days} days (%, rebased)", x=0.01, font=dict(size=12)))
    return charts._layout(fig, 340)


TIER_STYLE = {"MUST KNOW": ("🔴", "tos-red"), "IMPORTANT": ("🟠", "tos-amber"), "INTERESTING": ("🔵", "tos-blue"),
              "IGNORE FOR NOW": ("⚪", "")}
INFO_TAG = {"Confirmed": ("FACT", "tos-green"), "Reported": ("REPORTED", ""), "Analyst": ("OPINION", "tos-purple"),
            "Speculation": ("UNVERIFIED", "tos-red")}


def story_card(r: dict | pd.Series) -> str:
    tier_icon, tier_cls = TIER_STYLE.get(r["tier"], ("", ""))
    tag, tag_cls = next((v for k, v in INFO_TAG.items() if str(r.get("info_type", "")).startswith(k)), ("REPORTED", ""))
    pub = r.get("published_utc")
    pub_s = pd.Timestamp(pub).strftime("%d %b %H:%M UTC") if pub is not None and pd.notna(pub) else "time n/a"
    url = html.escape(r.get("url") or "#", quote=True)
    also = f' · also {html.escape(str(r["also_reported_by"])[:120])}' if r.get("also_reported_by") else ""
    impact = (f'<div style="font-size:0.74rem;color:#94A3B8;margin-top:3px;">Rule-based impact note '
              f'(interpretation): {html.escape(r["impact"])}</div>') if r.get("impact") else ""
    return (
        f'<div class="term-card" style="margin-bottom:6px;">'
        f'<div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">'
        f'<div>{ui.chip(tier_icon + " " + r["tier"], tier_cls)} {ui.chip(tag, tag_cls)} {ui.chip(r.get("region") or "")} '
        f'<span style="font-size:0.72rem;color:#64748B;">{html.escape(str(r.get("source", "")))} · {pub_s}{also}</span></div>'
        f'<a href="{url}" target="_blank" style="color:#38BDF8;font-size:0.75rem;text-decoration:none;white-space:nowrap;">Source ↗</a>'
        f'</div>'
        f'<div style="font-weight:600;font-size:0.9rem;color:#F1F5F9;margin-top:4px;">{html.escape(r["headline"])}</div>'
        f'<div style="font-size:0.72rem;color:#64748B;margin-top:2px;">score {r["score"]} · {html.escape(str(r.get("reasons", "")))}</div>'
        f'{impact}</div>'
    )


def story_list(ranked: pd.DataFrame, n: int = 12, tiers: tuple[str, ...] = ("MUST KNOW", "IMPORTANT", "INTERESTING"),
               empty: str = "No stories. Refresh news from the Daily Briefing or News page.") -> None:
    d = ranked[ranked["tier"].isin(tiers)].head(n) if len(ranked) else ranked
    if d is None or d.empty:
        ui.empty_state(empty)
        return
    st.markdown("".join(story_card(r) for _, r in d.iterrows()), unsafe_allow_html=True)


def unavailable_box(items: list[tuple[str, str, str]]) -> None:
    with st.expander("Not covered here (no authorised free source) — official links", expanded=False):
        for name, why, url in items:
            st.markdown(f"- **{name}** — {why} [Official source ↗]({url})")


def page_header(title: str, subtitle: str) -> None:
    st.markdown(f"## {title}")
    st.caption(subtitle)


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ----------------------------------------------------------------------------- Stage 2 cached accessors
@st.cache_data(ttl=900, show_spinner=False)
def _news_raw(days: int, nonce: int) -> pd.DataFrame:  # noqa: ARG001
    from tradingos.data.news import query_news
    return query_news(days=days, limit=6000)


def news_raw(days: int = 35) -> pd.DataFrame:
    return _news_raw(days, _nonce() + st.session_state.get("news_nonce", 0))


@st.cache_data(ttl=900, show_spinner=False)
def _geo_tagged(nonce: int) -> pd.DataFrame:  # noqa: ARG001
    from tradingos.intel import geopolitics
    return geopolitics.tag_news(news_raw(35))


def geo_tagged() -> pd.DataFrame:
    return _geo_tagged(_nonce() + st.session_state.get("news_nonce", 0))


@st.cache_data(ttl=900, show_spinner=False)
def _radar(nonce: int):  # noqa: ARG001
    from tradingos.intel import geopolitics, trends
    tab, detail, meta = trends.radar(news_raw(35), geopolitics.now_naive_utc())
    # series are not needed by most callers but are cheap; keep detail as-is
    return tab, detail, meta


def radar():
    return _radar(_nonce() + st.session_state.get("news_nonce", 0))


def news_refresh_button(key: str, label: str = "↻ Refresh news feeds") -> None:
    if st.button(label, key=key):
        from tradingos.data.news import refresh_news
        with st.spinner("Fetching RSS, Finnhub and official feeds…"):
            s = refresh_news([], max_age_days=35)
        bump_news()
        st.toast(f"{s['stored']} new · {s['duplicates']} duplicates · {s['stale']} stale dropped · {len(s['errors'])} errors")
