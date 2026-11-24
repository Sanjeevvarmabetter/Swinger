"""Shared Streamlit UI helpers: styling, terminal design system, badges, formatting, AI panels."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
import streamlit as st

from tradingos.config import load_config
from tradingos.data.base import NY, is_trading_day
from tradingos.settings import load_settings

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

/* Base layout & typography */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #F1F5F9;
}
.block-container {
    padding-top: 3.2rem;
    padding-bottom: 2.5rem;
    max-width: 1560px;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'Inter', sans-serif;
    letter-spacing: -0.02em;
    font-weight: 600;
    color: #F8FAFC;
    margin-top: 0.2rem;
    margin-bottom: 0.4rem;
}
h1 { font-size: 1.55rem; }
h2 { font-size: 1.25rem; }
h3 { font-size: 1.05rem; }

/* Institutional dark sidebar */
section[data-testid="stSidebar"] {
    background-color: #070A0F !important;
    border-right: 1px solid #151D2A !important;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarNav"] {
    padding-top: 0.4rem;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarNav"] ul li a {
    border-radius: 4px;
    margin: 1px 6px;
    padding: 6px 10px;
    font-size: 0.84rem;
    color: #94A3B8 !important;
    transition: all 0.12s ease;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarNav"] ul li a:hover {
    background-color: rgba(255, 255, 255, 0.04) !important;
    color: #F1F5F9 !important;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarNav"] ul li a[aria-current="page"] {
    background: rgba(56, 189, 248, 0.08) !important;
    border-left: 2px solid #38BDF8 !important;
    color: #38BDF8 !important;
    font-weight: 600 !important;
}

/* Metric styling */
div[data-testid="stMetric"] {
    background: #0E1420;
    border: 1px solid #1A2333;
    border-radius: 6px;
    padding: 10px 14px;
}
div[data-testid="stMetricLabel"] p {
    color: #8492A6;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
}
div[data-testid="stMetricValue"] div {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.35rem;
    font-weight: 600;
    color: #F8FAFC;
}
div[data-testid="stMetricDelta"] div {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    font-weight: 500;
}

/* Linear-style Tabs */
button[data-baseweb="tab"] {
    background-color: transparent !important;
    border: none !important;
    color: #8492A6 !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    padding: 8px 16px !important;
    border-bottom: 2px solid transparent !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #38BDF8 !important;
    border-bottom: 2px solid #38BDF8 !important;
    font-weight: 600 !important;
}

/* Border wrappers & containers */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #1A2333 !important;
    border-radius: 6px !important;
    background: #0D121D;
}

/* Institutional Terminal Cards */
.term-card {
    background: #0D131F;
    border: 1px solid #182233;
    border-radius: 6px;
    padding: 10px 12px;
    position: relative;
    transition: border-color 0.15s ease;
    margin-bottom: 8px;
}
.term-card:hover {
    border-color: #24334C;
}
.term-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
}
.term-label {
    font-size: 0.70rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #8492A6;
}
.term-value-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
}
.term-val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.25rem;
    font-weight: 700;
    color: #F8FAFC;
    line-height: 1.1;
}
.term-delta-pos {
    color: #10B981;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.76rem;
    font-weight: 600;
}
.term-delta-neg {
    color: #F43F5E;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.76rem;
    font-weight: 600;
}
.term-sub {
    font-size: 0.70rem;
    color: #64748B;
    margin-top: 3px;
    font-family: 'JetBrains Mono', monospace;
}

/* Badges & Chips */
.tos-chip {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 500;
    margin-right: 5px;
    border: 1px solid #1E293B;
    background: #0F172A;
    color: #94A3B8;
}
.tos-green { color: #10B981; border-color: rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.08); }
.tos-amber { color: #F59E0B; border-color: rgba(245, 158, 11, 0.35); background: rgba(245, 158, 11, 0.08); }
.tos-red   { color: #F43F5E; border-color: rgba(244, 63, 94, 0.35);  background: rgba(244, 63, 94, 0.08); }
.tos-blue  { color: #38BDF8; border-color: rgba(56, 189, 248, 0.35); background: rgba(56, 189, 248, 0.08); }
.tos-purple{ color: #A855F7; border-color: rgba(168, 85, 247, 0.35); background: rgba(168, 85, 247, 0.08); }
.tos-card  { background: #0E1420; border: 1px solid #1A2333; border-radius: 6px; padding: 12px 14px; margin-bottom: 10px; }
.tos-muted { color: #8492A6; font-size: 0.80rem; }
.tos-verdict { font-weight: 700; font-size: 0.95rem; padding: 3px 10px; border-radius: 4px; display: inline-block; }

/* Top Workstation Bar */
.top-workstation-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #090E17;
    border: 1px solid #162030;
    border-radius: 6px;
    padding: 8px 14px;
    margin-bottom: 14px;
}
.brand-title {
    font-size: 0.88rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #F1F5F9;
}
.brand-sub {
    font-size: 0.70rem;
    color: #64748B;
    letter-spacing: 0.02em;
}

/* Clean Form inputs & Buttons */
input[type="text"], input[type="number"], select {
    background-color: #0B1019 !important;
    border: 1px solid #1C2638 !important;
    color: #F1F5F9 !important;
    border-radius: 4px !important;
}
input:focus {
    border-color: #38BDF8 !important;
    box-shadow: 0 0 0 1px #38BDF833 !important;
}
button[kind="secondary"] {
    background-color: #0E1522 !important;
    border: 1px solid #1C273A !important;
    color: #E2E8F0 !important;
    border-radius: 4px !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    padding: 4px 10px !important;
    transition: all 0.12s ease !important;
}
button[kind="secondary"]:hover {
    background-color: #141E2F !important;
    border-color: #38BDF866 !important;
    color: #38BDF8 !important;
}
button[kind="primary"] {
    background-color: #0284C7 !important;
    border: 1px solid #38BDF8 !important;
    color: #FFFFFF !important;
    border-radius: 4px !important;
    font-weight: 600 !important;
}

/* Subtle scrollbars */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #080B10; }
::-webkit-scrollbar-thumb { background: #1E293B; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #334155; }
</style>
"""

FRESH_COLOR = {
    "Current": "tos-green",
    "Intraday": "tos-blue",
    "Stale": "tos-amber",
    "Very": "tos-red",
    "Missing": "tos-red",
    "Periodic": "tos-blue",
}

VERDICT_STYLE = {
    "Plan eligible": ("#10B981", "#092418"),
    "Watch": ("#38BDF8", "#081E2C"),
    "Wait": ("#F59E0B", "#261904"),
    "Avoid": ("#F43F5E", "#260A0E"),
}


def setup_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def flash(msg: str, kind: str = "success") -> None:
    """Queue a message that survives st.rerun()."""
    st.session_state.setdefault("_flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        getattr(st, kind)(msg)


def settings():
    return load_settings()


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
        color = "#10B981" if vals[-1] >= vals[0] else "#F43F5E"
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
    """Generates a high-density Bloomberg-style financial terminal metric card."""
    delta_html = ""
    is_pos = (delta_pct is not None and delta_pct > 0) or (delta and delta.startswith("+"))
    is_neg = (delta_pct is not None and delta_pct < 0) or (delta and delta.startswith("-"))
    if inverse:
        is_pos, is_neg = is_neg, is_pos

    delta_cls = "term-delta-pos" if is_pos else ("term-delta-neg" if is_neg else "tos-muted")
    arrow = "▲ " if is_pos else ("▼ " if is_neg else "")
    if delta:
        delta_html = f'<div class="{delta_cls}">{arrow}{html.escape(delta)}</div>'

    badge_html = ""
    if badge_label:
        badge_html = badge(badge_label, badge_color)

    spark_svg = sparkline_svg(sparkline_vals, width=82, height=22,
                              color="#10B981" if (not inverse and is_pos) or (inverse and is_neg) else "#F43F5E")
    spark_html = f'<div style="text-align:right;">{spark_svg}</div>' if spark_svg else ""
    sub_html = f'<div class="term-sub">{html.escape(sub)}</div>' if sub else ""

    return (
        f'<div class="term-card">'
        f'  <div class="term-card-header">'
        f'    <div class="term-label">{html.escape(title)}</div>'
        f'    <div>{badge_html}</div>'
        f'  </div>'
        f'  <div class="term-value-row">'
        f'    <div class="term-val">{html.escape(str(value))}</div>'
        f'    {delta_html}'
        f'  </div>'
        f'  <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:2px;">'
        f'    {sub_html}'
        f'    {spark_html}'
        f'  </div>'
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
            "dot_color": "#38BDF8",
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
            "dot_color": "#10B981",
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
            "dot_color": "#F59E0B",
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
    """Renders the top institutional workstation navigation bar."""
    sess = market_session_info()
    cfg = load_config()

    col_brand, col_clock, col_status, col_act = st.columns([2.5, 2.5, 2.8, 1.2])
    with col_brand:
        st.markdown(
            f'<div style="padding-top:2px;">'
            f'<span class="brand-title">GLOBAL MARKET INTEL</span> '
            f'<span class="brand-sub">· AI TRADING OS</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_clock:
        now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.markdown(
            f'<div style="font-size:0.76rem;color:#94A3B8;padding-top:4px;font-family:\'JetBrains Mono\',monospace;">'
            f'<span>NEW YORK: <strong style="color:#F1F5F9;">{sess["ny_time"]}</strong></span> '
            f'<span style="color:#475569;">|</span> <span>UTC: {now_utc}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_status:
        st.markdown(
            f'<div style="display:flex;align-items:center;padding-top:2px;">'
            f'<span class="{sess["badge_cls"]}" style="margin-right:6px;">'
            f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;'
            f'background-color:{sess["dot_color"]};margin-right:5px;"></span>'
            f'{sess["status"]}'
            f'</span>'
            f'<span style="font-size:0.72rem;color:#8492A6;">{sess["next_event"]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_act:
        if show_refresh:
            if st.button("↻ SYNC", key="_top_sync_btn", help="Sync latest market data", width="stretch"):
                from tradingos.ui.state import refresh_market
                refresh_market()
                st.rerun()

    st.markdown('<div style="border-bottom: 1px solid #162030; margin-bottom: 12px;"></div>', unsafe_allow_html=True)


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


def verdict_badge(verdict: str) -> None:
    fg, bg = VERDICT_STYLE.get(verdict, ("#E2E8F0", "#1E293B"))
    st.markdown(
        f'<span class="tos-verdict" style="color:{fg};background:{bg};border:1px solid {fg}44">'
        f'{html.escape(verdict)}</span>',
        unsafe_allow_html=True,
    )


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
        return "color: #10B981" if v > 0 else "color: #F43F5E" if v < 0 else ""
    fmt = {col: "{:+.2f}" for col in cols if col in df.columns}
    return df.style.map(c, subset=[col for col in cols if col in df.columns]).format(fmt, na_rep="—")


def gemini_panel(key: str, label: str, fn: Callable[[], str], help_text: str = "") -> None:
    """Button → run AI synthesis → keep result in session. Shows clear status when not configured."""
    cfg = load_config()
    state_key = f"ai_{key}"
    cols = st.columns([1.2, 3])
    active_model = f"Groq ({cfg.groq_model})" if cfg.groq_configured else f"Gemini ({cfg.gemini_model})"
    with cols[0]:
        clicked = st.button(
            f"✨ {label}",
            key=f"btn_{key}",
            disabled=not cfg.ai_configured,
            help=help_text or f"Sends Python-computed data to {active_model} for interpretation.",
            type="primary" if cfg.ai_configured else "secondary",
        )
    with cols[1]:
        if not cfg.ai_configured:
            st.caption("AI not configured — add GROQ_API_KEY (free) or GEMINI_API_KEY to .env or Streamlit secrets. "
                       "All deterministic analysis still works.")
        else:
            st.caption(f"Engine: <code>{active_model}</code> · Interprets Python-computed data; no live web access.",
                       unsafe_allow_html=True)
    if clicked:
        from tradingos.ai.gemini import GeminiError
        with st.spinner("AI is analysing the supplied data…"):
            try:
                st.session_state[state_key] = fn()
            except GeminiError as e:
                st.session_state[state_key] = None
                st.error(str(e))
            except Exception as e:
                st.session_state[state_key] = None
                st.error(f"AI analysis failed: {type(e).__name__}: {e}")
    if st.session_state.get(state_key):
        with st.container(border=True):
            st.markdown(st.session_state[state_key])
            st.caption("AI interpretation of supplied data — not financial advice. Verify facts against sources.")


def empty_state(msg: str) -> None:
    st.markdown(f'<div class="tos-card tos-muted" style="text-align:center;padding:18px;">{html.escape(msg)}</div>',
                unsafe_allow_html=True)


def disclaimer() -> None:
    st.caption("Personal research tool. Data is delayed/end-of-day from free sources and may be wrong or missing. "
               "Nothing here is financial advice or an order. No broker connection exists.")
