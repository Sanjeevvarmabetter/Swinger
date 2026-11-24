"""Shared Streamlit UI helpers: design system CSS, page header, badges, number formatting, AI panels."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
import streamlit as st

from tradingos.config import load_config
from tradingos.data.base import NY, is_trading_day

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ---------------------------------------------------------------- design tokens */
:root {
  --bg: #0A0D12; --surface: #10151D; --surface-2: #151B25; --border: #1F2734; --border-strong: #2B3546;
  --text: #E6EAF0; --text-strong: #F5F7FA; --muted: #8C96A8; --faint: #5F6B7E;
  --accent: #4EA8F2; --accent-soft: rgba(78,168,242,0.10);
  --pos: #2FBF71; --neg: #EF5B67; --warn: #E9A23B; --violet: #A78BFA;
  --radius: 8px; --radius-sm: 6px;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px;
  --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* ---------------------------------------------------------------- base */
html, body, .stApp { background: var(--bg); color: var(--text); font-family: var(--sans); }
.stApp [data-testid="stMarkdownContainer"] { font-size: 0.95rem; line-height: 1.6; }
.block-container { padding-top: 3.6rem; padding-bottom: 3rem; padding-left: 2rem; padding-right: 2rem;
                   max-width: 1480px; }
header[data-testid="stHeader"] { background: rgba(10,13,18,0.85); backdrop-filter: blur(6px); }
[data-testid="stAppDeployButton"], [data-testid="stDecoration"] { display: none !important; }
h1, h2, h3, h4, h5 { font-family: var(--sans); letter-spacing: -0.015em; color: var(--text-strong); font-weight: 600; }
.stApp h1 { font-size: 1.5rem; margin: 0.2rem 0 0.3rem; }
.stApp h2 { font-size: 1.25rem; margin: 1.1rem 0 0.4rem; padding: 0; }
.stApp h3 { font-size: 1.05rem; margin: 0.9rem 0 0.3rem; padding: 0; }
.stApp h4 { font-size: 0.95rem; margin: 0.7rem 0 0.25rem; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }
a { color: var(--accent); }
hr { border-color: var(--border) !important; margin: 1rem 0 !important; }

/* page header */
.pg-title { font-size: 1.45rem; font-weight: 650; color: var(--text-strong); letter-spacing: -0.02em;
            margin: 0 0 2px 0; line-height: 1.25; }
.pg-sub { color: var(--muted); font-size: 0.86rem; line-height: 1.5; margin-bottom: var(--s3); max-width: 900px; }

/* status strip */
.status-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; font-size: 0.76rem;
                color: var(--muted); font-family: var(--mono); min-height: 32px; }
.status-strip b { color: var(--text); font-weight: 500; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }

/* ---------------------------------------------------------------- sidebar */
section[data-testid="stSidebar"] { background: #080B10 !important; border-right: 1px solid var(--border) !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a { border-radius: var(--radius-sm); margin: 1px 6px;
    padding: 6px 10px; min-height: 36px; color: var(--muted) !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover { background: rgba(255,255,255,0.04) !important;
    color: var(--text) !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
    background: var(--accent-soft) !important; color: var(--text-strong) !important; font-weight: 600 !important;
    box-shadow: inset 2px 0 0 var(--accent); }
[data-testid="stNavSectionHeader"] { color: var(--faint) !important; font-size: 0.7rem !important;
    text-transform: uppercase; letter-spacing: 0.08em; }

/* ---------------------------------------------------------------- controls */
.stButton > button, .stDownloadButton > button, [data-testid="stLinkButton"] a, .stFormSubmitButton > button {
    border-radius: var(--radius-sm) !important; min-height: 38px; font-weight: 500 !important; font-size: 0.86rem !important; }
button[kind="secondary"] { background: var(--surface) !important; border: 1px solid var(--border-strong) !important;
    color: var(--text) !important; }
button[kind="secondary"]:hover { border-color: var(--accent) !important; color: var(--text-strong) !important; }
button[kind="primary"] { background: #2F7FD1 !important; border: 1px solid #2F7FD1 !important; color: #fff !important; }
button[kind="primary"]:hover { background: #3A8DE0 !important; }
button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible, [role="tab"]:focus-visible,
[role="combobox"]:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 2px; }
[data-testid="stChatInput"] textarea:focus-visible { outline: none !important; }
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { background: var(--surface) !important;
    border-color: var(--border-strong) !important; border-radius: var(--radius-sm) !important; }

/* tabs: compact, scrollable */
[data-baseweb="tab-list"] { gap: 2px; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid var(--border); }
[data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
button[data-baseweb="tab"] { background: transparent !important; color: var(--muted) !important;
    font-size: 0.86rem !important; padding: 8px 12px !important; min-height: 40px; white-space: nowrap; }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--text-strong) !important; font-weight: 600 !important; }
[data-baseweb="tab-highlight"] { background: var(--accent) !important; }
[data-baseweb="tab-border"] { display: none; }

/* containers / expanders / metrics */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) { border-radius: var(--radius); }
[data-testid="stExpander"] details { border: 1px solid var(--border) !important; border-radius: var(--radius) !important;
    background: var(--surface); }
[data-testid="stExpander"] summary { min-height: 42px; }
[data-testid="stExpander"] summary p { font-weight: 500; font-size: 0.9rem; }
div[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 10px 12px; }
div[data-testid="stMetricLabel"] p { color: var(--muted); font-size: 0.72rem; text-transform: uppercase;
    letter-spacing: 0.05em; font-weight: 600; }
div[data-testid="stMetricValue"] div { font-family: var(--mono); font-size: 1.25rem; font-weight: 600; }
[data-testid="stAlert"] { border-radius: var(--radius); }

/* ---------------------------------------------------------------- markdown content (AI reports, briefings) */
.stApp [data-testid="stMarkdownContainer"] table { display: block; max-width: 100%; overflow-x: auto;
    border-collapse: collapse; font-size: 0.86rem; margin: 0.6rem 0 1rem; -webkit-overflow-scrolling: touch; }
.stApp [data-testid="stMarkdownContainer"] th { background: var(--surface-2); color: var(--text-strong); font-weight: 600;
    text-align: left; white-space: nowrap; }
.stApp [data-testid="stMarkdownContainer"] th, .stApp [data-testid="stMarkdownContainer"] td {
    border: 1px solid var(--border); padding: 6px 10px; vertical-align: top; }
.stApp [data-testid="stMarkdownContainer"] td { font-variant-numeric: tabular-nums; }
.stApp [data-testid="stMarkdownContainer"] tr:nth-child(even) td { background: rgba(255,255,255,0.015); }
.stApp [data-testid="stMarkdownContainer"] pre { max-width: 100%; overflow-x: auto; }
.stApp [data-testid="stMarkdownContainer"] code { font-family: var(--mono); font-size: 0.84em; word-break: break-word; }
.stApp [data-testid="stMarkdownContainer"] blockquote { border-left: 3px solid var(--warn); background: rgba(233,162,59,0.06);
    margin: 0.6rem 0; padding: 6px 12px; color: var(--text); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.stApp [data-testid="stMarkdownContainer"] ul, .stApp [data-testid="stMarkdownContainer"] ol { padding-left: 1.3rem; }
.stApp [data-testid="stMarkdownContainer"] li { margin: 0.15rem 0; }
.stApp [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stMarkdownContainer"] li { overflow-wrap: anywhere; }
.report h2 { font-size: 1.08rem; border-bottom: 1px solid var(--border); padding-bottom: 4px; margin-top: 1.2rem; }

/* ---------------------------------------------------------------- cards, chips, tiles */
.term-card, .tos-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 10px 12px; margin-bottom: 8px; min-width: 0; }
.term-card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 4px 6px; flex-wrap: wrap; }
.tile-grid .term-card-header { flex-wrap: nowrap; }
.term-label { font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted);
    line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.term-value-row { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; flex-wrap: wrap;
    margin-top: 4px; }
.term-val { font-family: var(--mono); font-size: 1.15rem; font-weight: 600; color: var(--text-strong); line-height: 1.15; }
.term-delta-pos, .term-delta-neg { font-family: var(--mono); font-size: 0.78rem; font-weight: 600; white-space: nowrap; }
.term-delta-pos { color: var(--pos); } .term-delta-neg { color: var(--neg); }
.term-sub { font-size: 0.7rem; color: var(--faint); font-family: var(--mono); margin-top: 2px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
.term-foot { display: flex; justify-content: space-between; align-items: flex-end; gap: 6px; margin-top: 2px; min-width: 0; }
.tile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 172px), 1fr)); gap: 8px;
    margin-bottom: 8px; }
.tile-grid .term-card { margin-bottom: 0; }
.fresh-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; flex: none; margin-top: 4px; }

.tos-chip { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 0.72rem;
    font-weight: 500; margin: 0 4px 4px 0; border: 1px solid var(--border-strong); background: var(--surface);
    color: var(--muted); white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.tos-green { color: var(--pos); border-color: rgba(47,191,113,0.35); background: rgba(47,191,113,0.08); }
.tos-amber { color: var(--warn); border-color: rgba(233,162,59,0.35); background: rgba(233,162,59,0.08); }
.tos-red   { color: var(--neg); border-color: rgba(239,91,103,0.35); background: rgba(239,91,103,0.08); }
.tos-blue  { color: var(--accent); border-color: rgba(78,168,242,0.35); background: var(--accent-soft); }
.tos-purple{ color: var(--violet); border-color: rgba(167,139,250,0.35); background: rgba(167,139,250,0.08); }
.tos-muted { color: var(--muted); font-size: 0.84rem; }
.chips { display: flex; flex-wrap: wrap; align-items: center; }

/* story / briefing items */
.story { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px;
    margin-bottom: 8px; min-width: 0; }
.story.must { border-left: 3px solid var(--neg); } .story.imp { border-left: 3px solid var(--warn); }
.story.int { border-left: 3px solid var(--accent); }
.story-head { font-weight: 600; font-size: 0.95rem; color: var(--text-strong); line-height: 1.4; margin: 4px 0 2px;
    overflow-wrap: anywhere; }
.story-head a { color: inherit; text-decoration: none; } .story-head a:hover { text-decoration: underline; }
.story-body { font-size: 0.85rem; color: var(--text); opacity: 0.9; line-height: 1.5; overflow-wrap: anywhere; }
.story-meta { font-size: 0.74rem; color: var(--faint); margin-top: 4px; overflow-wrap: anywhere; }
.story-meta a { color: var(--accent); text-decoration: none; white-space: nowrap; padding: 6px 0; }
.sec-title { font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted);
    margin: 18px 0 8px; display: flex; align-items: center; gap: 8px; }
.sec-title .count { color: var(--faint); font-weight: 500; }

/* live newsroom */
.video-wrap { position: relative; width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: var(--radius);
    overflow: hidden; border: 1px solid var(--border); }
.video-wrap iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }

/* X posts */
.xpost { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px;
    margin-bottom: 8px; }
.xpost .who { font-size: 0.8rem; color: var(--text-strong); font-weight: 600; }
.xpost .who span { color: var(--faint); font-weight: 400; }
.xpost .txt { font-size: 0.88rem; line-height: 1.5; margin: 4px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.xpost .meta { font-size: 0.72rem; color: var(--faint); }

/* chat */
[data-testid="stChatMessage"] { background: transparent; padding: 0.5rem 0; gap: 0.6rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px; }
[data-testid="stChatMessageContent"] { min-width: 0; overflow-wrap: anywhere; }
.msg-meta { font-size: 0.72rem; color: var(--faint); margin-top: 6px; }
.sources-box { border-top: 1px solid var(--border); margin-top: 10px; padding-top: 6px; font-size: 0.82rem; }

/* status row: strip shrinks, refresh button stays on the same line */
.st-key-topbar { flex-wrap: nowrap !important; }
.st-key-topbar > div:first-child { min-width: 0; flex: 1 1 auto; }

/* mobile bottom navigation (rendered by app.py, only visible < 768px) */
.st-key-mnav { display: none !important; }

/* scrollbars */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #263041; border-radius: 3px; }

/* ---------------------------------------------------------------- tablet */
@media (max-width: 1024px) {
  .block-container { padding-left: 1.25rem; padding-right: 1.25rem; }
}
/* ---------------------------------------------------------------- phone */
@media (max-width: 767px) {
  .block-container { padding: 3.4rem 1rem 6.5rem 1rem !important; }
  .stApp [data-testid="stMarkdownContainer"] { font-size: 0.94rem; }
  .pg-title { font-size: 1.22rem; } .pg-sub { font-size: 0.82rem; }
  .stApp h2 { font-size: 1.1rem; } .stApp h3 { font-size: 1rem; }
  .hide-sm { display: none !important; }
  .tile-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
  .term-card { padding: 7px 9px; }
  .term-value-row { margin-top: 2px; flex-wrap: nowrap; }
  .term-val { font-size: 0.98rem; }
  .term-delta-pos, .term-delta-neg { font-size: 0.72rem; }
  .term-sub { font-size: 0.66rem; }
  .term-foot { margin-top: 0; align-items: center; }
  .term-foot svg { height: 14px; width: auto; }
  .status-strip { font-size: 0.72rem; gap: 2px 10px; }
  .stButton > button, .stDownloadButton > button, [data-testid="stLinkButton"] a { min-height: 44px; }
  button[data-baseweb="tab"] { padding: 8px 10px !important; font-size: 0.82rem !important; }
  [data-testid="stChatMessage"] [data-testid*="Avatar"] { width: 1.6rem; height: 1.6rem; }
  /* bottom nav */
  .st-key-mnav { display: flex !important; position: fixed; left: 0; right: 0; bottom: 0; z-index: 999990;
      background: rgba(10,13,18,0.97); border-top: 1px solid var(--border); padding: 4px 4px calc(4px + env(safe-area-inset-bottom));
      justify-content: space-around; flex-wrap: nowrap !important; gap: 0 !important; backdrop-filter: blur(8px); }
  .st-key-mnav > div { flex: 1 1 0 !important; min-width: 0 !important; width: auto !important; }
  .st-key-mnav [data-testid="stPageLink"] a { display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 1px; min-height: 50px; padding: 4px 2px; border-radius: var(--radius-sm); text-decoration: none; }
  .st-key-mnav [data-testid="stPageLink"] a p { font-size: 0.66rem !important; color: var(--muted); margin: 0;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
  .st-key-mnav [data-testid="stPageLink"] a span { color: var(--muted); }
  .st-key-mnav [data-testid="stPageLink"] a[aria-current="page"] p,
  .st-key-mnav [data-testid="stPageLink"] a[aria-current="page"] span { color: var(--accent) !important; }
  .st-key-mnav [data-testid="stPageLink"] a[aria-current="page"] { background: var(--accent-soft); }
}
</style>
"""

POS, NEG, MUTED = "#2FBF71", "#EF5B67", "#8C96A8"

FRESH_COLOR = {
    "Current": "tos-green",
    "Intraday": "tos-blue",
    "Stale": "tos-amber",
    "Very": "tos-red",
    "Missing": "tos-red",
    "Periodic": "tos-blue",
}

def setup_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def flash(msg: str, kind: str = "success") -> None:
    """Queue a message that survives st.rerun()."""
    st.session_state.setdefault("_flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        getattr(st, kind)(msg)


def safe_url(url: str | None) -> str:
    """Only http(s) links are rendered; anything else (javascript:, data:, relative) becomes '#'."""
    u = str(url or "").strip()
    return html.escape(u, quote=True) if u.lower().startswith(("https://", "http://")) else "#"


def chip(text: str, cls: str = "") -> str:
    return f'<span class="tos-chip {cls}">{html.escape(str(text))}</span>'


def badge(text: str, variant: str = "neutral") -> str:
    cls_map = {
        "green": "tos-green",
        "red": "tos-red",
        "amber": "tos-amber",
        "blue": "tos-blue",
        "purple": "tos-purple",
        "neutral": "",
    }
    return chip(text, cls_map.get(variant, ""))


def sparkline_svg(values: list[float] | pd.Series | None, width: int = 86, height: int = 24,
                  color: str | None = None) -> str:
    """Generates a responsive SVG sparkline without any external client-side libraries."""
    if values is None:
        return ""
    if isinstance(values, pd.Series):
        vals = [float(v) for v in values.dropna().tolist()]
    else:
        vals = [float(v) for v in values if v is not None and not (isinstance(v, float) and pd.isna(v))]
    if len(vals) < 2:
        return ""
    mn, mx = min(vals), max(vals)
    rng = mx - mn
    if rng == 0:
        rng = 1.0
    pad = 2.0
    h_eff = height - (pad * 2)
    step = width / (len(vals) - 1)
    pts = []
    for i, v in enumerate(vals):
        x = round(i * step, 1)
        y = round(height - pad - ((v - mn) / rng) * h_eff, 1)
        pts.append(f"{x},{y}")
    polyline = " ".join(pts)
    if color is None:
        color = POS if vals[-1] >= vals[0] else NEG
    grad_id = f"sg_{abs(hash(polyline)) % 100000}"
    fill_area = f"0,{height} {polyline} {width},{height}"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="overflow:visible;vertical-align:middle;display:inline-block;">'
        f'<defs><linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.22"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0.0"/>'
        f'</linearGradient></defs>'
        f'<polygon points="{fill_area}" fill="url(#{grad_id})"/>'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def terminal_metric_card(
    title: str,
    value: str,
    delta: str | None = None,
    delta_pct: float | None = None,
    sub: str | None = None,
    sparkline_vals: list[float] | pd.Series | None = None,
    inverse: bool = False,
    badge_label: str | None = None,
    badge_color: str = "blue",
) -> str:
    """Compact market tile: label + freshness dot, value + signed change, sub line + sparkline.

    `inverse` swaps colours for instruments where a rise is risk-negative (VIX). The freshness badge is shown as a
    coloured dot with an accessible label/tooltip so tiles stay narrow enough for two per row on phones.
    """
    is_pos = (delta_pct is not None and delta_pct > 0) or bool(delta and delta.startswith("+"))
    is_neg = (delta_pct is not None and delta_pct < 0) or bool(delta and delta.startswith("-"))
    good, bad = (is_neg, is_pos) if inverse else (is_pos, is_neg)
    delta_cls = "term-delta-pos" if good else ("term-delta-neg" if bad else "tos-muted")
    arrow = "▲ " if is_pos else ("▼ " if is_neg else "")
    delta_html = f'<span class="{delta_cls}">{arrow}{html.escape(delta)}</span>' if delta else ""
    dot = ""
    if badge_label:
        col = {"green": "var(--pos)", "blue": "var(--accent)", "amber": "var(--warn)", "red": "var(--neg)"}.get(
            badge_color, "var(--muted)")
        dot = (f'<span class="fresh-dot" style="background:{col}" title="{html.escape(badge_label)}" '
               f'role="img" aria-label="Freshness: {html.escape(badge_label)}"></span>')
    spark = sparkline_svg(sparkline_vals, width=64, height=20,
                          color=POS if good else (NEG if bad else MUTED))
    sub_html = f'<div class="term-sub">{html.escape(sub)}</div>' if sub else "<div></div>"
    return (
        f'<div class="term-card">'
        f'<div class="term-card-header"><div class="term-label" title="{html.escape(title)}">{html.escape(title)}</div>{dot}</div>'
        f'<div class="term-value-row"><div class="term-val">{html.escape(str(value))}</div>{delta_html}</div>'
        f'<div class="term-foot">{sub_html}<div style="flex:none">{spark}</div></div>'
        f'</div>'
    )


def market_session_info() -> dict[str, Any]:
    """Accurately calculates US Market Session status using America/New_York timezone and NYSE calendar."""
    now_ny = datetime.now(timezone.utc).astimezone(NY)
    is_td = is_trading_day(now_ny.date())
    cur_time = now_ny.time()
    t_hour, t_min = cur_time.hour, cur_time.minute
    t_val = t_hour * 60 + t_min

    # Session boundaries in minutes from midnight ET
    # Pre-market: 04:00 (240m) to 09:30 (570m)
    # Regular: 09:30 (570m) to 16:00 (960m)
    # After-hours: 16:00 (960m) to 20:00 (1200m)
    if not is_td:
        if now_ny.weekday() in (5, 6):
            return {
                "status": "WEEKEND CLOSED",
                "label": "Weekend · Markets Closed",
                "color": "neutral",
                "badge_cls": "tos-chip",
                "dot_color": "#64748B",
                "next_event": "Pre-market opens Monday 04:00 ET",
                "ny_time": now_ny.strftime("%H:%M:%S ET"),
                "is_active": False,
            }
        else:
            return {
                "status": "HOLIDAY CLOSED",
                "label": "NYSE Holiday · Markets Closed",
                "color": "neutral",
                "badge_cls": "tos-chip",
                "dot_color": "#64748B",
                "next_event": "Reopens next scheduled trading session",
                "ny_time": now_ny.strftime("%H:%M:%S ET"),
                "is_active": False,
            }

    if t_val < 240:
        return {
            "status": "OVERNIGHT",
            "label": "Overnight · Markets Closed",
            "color": "neutral",
            "badge_cls": "tos-chip",
            "dot_color": "#64748B",
            "next_event": "Pre-market opens 04:00 ET",
            "ny_time": now_ny.strftime("%H:%M:%S ET"),
            "is_active": False,
        }
    elif 240 <= t_val < 570:
        return {
            "status": "PRE-MARKET",
            "label": "Pre-Market Session (04:00 – 09:30 ET)",
            "color": "blue",
            "badge_cls": "tos-chip tos-blue",
            "dot_color": "#4EA8F2",
            "next_event": "Regular session opens at 09:30 ET",
            "ny_time": now_ny.strftime("%H:%M:%S ET"),
            "is_active": True,
        }
    elif 570 <= t_val < 960:
        return {
            "status": "REGULAR SESSION",
            "label": "Regular Trading Session (09:30 – 16:00 ET)",
            "color": "green",
            "badge_cls": "tos-chip tos-green",
            "dot_color": "#2FBF71",
            "next_event": "Closes at 16:00 ET",
            "ny_time": now_ny.strftime("%H:%M:%S ET"),
            "is_active": True,
        }
    elif 960 <= t_val < 1200:
        return {
            "status": "AFTER-HOURS",
            "label": "After-Hours Session (16:00 – 20:00 ET)",
            "color": "amber",
            "badge_cls": "tos-chip tos-amber",
            "dot_color": "#E9A23B",
            "next_event": "After-hours ends 20:00 ET",
            "ny_time": now_ny.strftime("%H:%M:%S ET"),
            "is_active": True,
        }
    else:
        return {
            "status": "OVERNIGHT",
            "label": "Overnight · Markets Closed",
            "color": "neutral",
            "badge_cls": "tos-chip",
            "dot_color": "#64748B",
            "next_event": "Pre-market opens tomorrow 04:00 ET",
            "ny_time": now_ny.strftime("%H:%M:%S ET"),
            "is_active": False,
        }


def render_top_bar(show_refresh: bool = True) -> None:
    """Slim status strip: US session state + New York / India / UTC time at page render, optional refresh button."""
    from zoneinfo import ZoneInfo
    sess = market_session_info()
    now = datetime.now(timezone.utc)
    ist = now.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M IST")
    ny = now.astimezone(NY).strftime("%H:%M ET")
    strip = (
        f'<div class="status-strip" role="status">'
        f'<span><span class="dot" style="background:{sess["dot_color"]}"></span><b>US {html.escape(sess["status"].title())}</b></span>'
        f'<span>{ny}</span><span>{ist}</span><span class="hide-sm">{now:%H:%M} UTC</span>'
        f'<span class="hide-sm">{html.escape(sess["next_event"])}</span>'
        f'</div>'
    )
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key="topbar"):
        st.markdown(strip, unsafe_allow_html=True, width="stretch")
        if show_refresh:
            if st.button("Refresh", icon=":material/refresh:", key="_top_sync_btn",
                         help="Re-download market data (otherwise cached for 15 minutes)"):
                from tradingos.ui.state import refresh_market
                refresh_market()
                st.rerun()


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<h1 class="pg-title">{html.escape(title)}</h1>'
                + (f'<div class="pg-sub">{html.escape(subtitle)}</div>' if subtitle else ""), unsafe_allow_html=True)


def freshness_badge(meta: dict | None, label: str = "Data") -> None:
    if not meta:
        st.markdown(chip(f"{label}: unavailable", "tos-red"), unsafe_allow_html=True)
        return
    fresh = meta.get("freshness", "Missing")
    cls = next((v for k, v in FRESH_COLOR.items() if fresh.startswith(k)), "")
    parts = [
        chip(f"{label}: {meta.get('source', '?')}"),
        chip(f"As of {meta.get('data_as_of') or 'n/a'}"),
        chip(fresh, cls),
        chip(f"Retrieved {meta.get('retrieved_at_utc', '?')}"),
    ]
    if meta.get("missing"):
        parts.append(chip(f"Missing: {', '.join(meta['missing'][:8])}" + ("…" if len(meta["missing"]) > 8 else ""),
                          "tos-amber"))
    if meta.get("error"):
        parts.append(chip(f"Error: {meta['error'][:80]}", "tos-red"))
    st.markdown(" ".join(parts), unsafe_allow_html=True)


def money(x, dp: int = 2) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"-${abs(x):,.{dp}f}" if x < 0 else f"${x:,.{dp}f}"


def pct(x, dp: int = 1, sign: bool = True) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:+.{dp}f}%" if sign else f"{x:.{dp}f}%"


def num(x, dp: int = 2) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:,.{dp}f}"


def color_pct_cols(df: pd.DataFrame, cols: list[str]):
    def c(v):
        if v is None or pd.isna(v) or not isinstance(v, (int, float)):
            return ""
        return "color: #2FBF71" if v > 0 else "color: #EF5B67" if v < 0 else ""
    fmt = {col: "{:+.2f}" for col in cols if col in df.columns}
    return df.style.map(c, subset=[col for col in cols if col in df.columns]).format(fmt, na_rep="—")


def ai_engine_label() -> str:
    cfg = load_config()
    if cfg.groq_configured and cfg.ai_provider in ("groq", "auto"):
        return f"Groq · {cfg.groq_model}"
    if cfg.gemini_configured:
        return f"Gemini · {cfg.gemini_model}"
    return "not configured"


def render_ai_markdown(text: str, allowed_urls=None) -> dict:
    """Render an AI answer after deterministic clean-up (tables, fences, JSON, unverified links, coloured moves)."""
    from tradingos.ai.formatting import clean_answer
    md, report = clean_answer(text, allowed_urls=allowed_urls)
    st.markdown(md)
    if report.get("links_removed"):
        st.caption(f"{report['links_removed']} link(s) not present in the source data were removed.")
    return report


def _payload_urls(obj, out: set[str] | None = None) -> set[str]:
    """All URLs that appear in a payload (any nested dict/list/DataFrame) — the only links an AI answer may keep."""
    if out is None:
        from tradingos.ai.gemini import to_jsonable
        obj = to_jsonable(obj)
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http"):
                out.add(v)
            else:
                _payload_urls(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            if isinstance(v, str) and v.startswith("http"):
                out.add(v)
            else:
                _payload_urls(v, out)
    return out


def gemini_panel(key: str, label: str, fn: Callable[[], str], help_text: str = "",
                 payload_for_links: Any = None) -> None:
    """Button → AI interpretation of Python-computed data → kept in session. Clear status when not configured.

    If `payload_for_links` is given, links in the answer are kept only when their URL appears in that payload.
    """
    cfg = load_config()
    state_key = f"ai_{key}"
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        clicked = st.button(label, key=f"btn_{key}", icon=":material/auto_awesome:", disabled=not cfg.ai_configured,
                            help=help_text or "Sends the Python-computed data on this page to the AI for interpretation.",
                            type="primary" if cfg.ai_configured else "secondary")
        st.caption("AI not configured — add GROQ_API_KEY or GEMINI_API_KEY to .env. Everything else works without it."
                   if not cfg.ai_configured else f"Engine: {ai_engine_label()} · interprets this page's data only")
    if clicked:
        from tradingos.ai.gemini import GeminiError
        with st.spinner("AI is analysing the supplied data…"):
            try:
                st.session_state[state_key] = fn()
                st.session_state[state_key + "_at"] = datetime.now(timezone.utc).strftime("%d %b %H:%M UTC")
            except GeminiError as e:
                st.session_state[state_key] = None
                st.error(f"AI unavailable: {e}")
            except Exception as e:  # noqa: BLE001
                st.session_state[state_key] = None
                st.error(f"AI analysis failed: {type(e).__name__}: {e}")
    if st.session_state.get(state_key):
        with st.container(border=True):
            allowed = _payload_urls(payload_for_links) if payload_for_links is not None else None
            render_ai_markdown(st.session_state[state_key], allowed_urls=allowed)
            st.caption(f"AI interpretation of the data above · generated {st.session_state.get(state_key + '_at', '')} · "
                       "not financial advice — verify against the cited sources.")


def empty_state(msg: str) -> None:
    st.markdown(f'<div class="tos-card tos-muted" style="text-align:center;padding:18px;">{html.escape(msg)}</div>',
                unsafe_allow_html=True)


def disclaimer() -> None:
    st.caption("Personal research tool. Market data is delayed or end-of-day from free sources and may be wrong or "
               "missing. Nothing here is financial advice.")
