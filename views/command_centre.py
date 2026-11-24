"""Overview — Institutional Trading Command Center."""
from __future__ import annotations

import html
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

from tradingos.ai import gemini
from tradingos.analysis.scanner import latest_scan
from tradingos.data.base import NY
from tradingos.data.news import query_news
from tradingos.journal.service import account_state, sizing_equity, trades_dataframe
from tradingos.services import ai_payload_from_context, latest_prices
from tradingos.ui import components as ui
from tradingos.ui.state import market_ctx, refresh_market, select_ticker
from tradingos.watchlist import watchlist_snapshot

cfg = ui.settings()

# Top workstation header
ui.render_top_bar(show_refresh=True)

with st.spinner("Syncing market overview data (cached 15m)..."):
    mc = market_ctx(include_macro=False)

# -----------------------------------------------------------------------------
# SECTION A: Market Overview (8 Core Market Assets)
# -----------------------------------------------------------------------------
st.markdown(
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
    '  <span style="font-size:0.88rem;font-weight:700;letter-spacing:0.06em;color:#CBD5E1;text-transform:uppercase;">'
    '    Market Pulse · Key Benchmark Assets'
    '  </span>'
    '</div>',
    unsafe_allow_html=True,
)

idx = mc["indices"]
ui.freshness_badge(mc["index_data_meta"], "Index Data")

if not idx.empty:
    cols = st.columns(4)
    # Target symbols in priority order
    priority_syms = ["SPY", "QQQ", "IWM", "DIA", "^VIX", "GLD", "^TNX", "DX-Y.NYB"]
    displayed = []

    for sym in priority_syms:
        match = idx[idx["Symbol"] == sym]
        if not match.empty:
            displayed.append(match.iloc[0])

    # If some not found, append others from idx
    for _, r in idx.iterrows():
        if r["Symbol"] not in [d["Symbol"] for d in displayed] and len(displayed) < 8:
            displayed.append(r)

    # Render top row (4) and bottom row (4)
    for i, r in enumerate(displayed[:8]):
        col = cols[i % 4]
        with col:
            delta_val = None if pd.isna(r.get("1D %")) else f"{r['1D %']:+.2f}%"
            abs_val = None
            if "1D $" in r and pd.notna(r["1D $"]):
                abs_val = f"{r['1D $']:+.2f}"
            elif delta_val:
                abs_val = delta_val

            is_inv = r["Symbol"] in ("^VIX",)
            spk = r.get("sparkline")

            sub_text = f"As of {r.get('As of', 'Today')}"
            if abs_val and delta_val and abs_val != delta_val:
                sub_text = f"{abs_val} (1D) · {sub_text}"

            card_html = ui.terminal_metric_card(
                title=f"{r['Name']} ({r['Symbol']})",
                value=ui.num(r["Last"]),
                delta=delta_val,
                delta_pct=r.get("1D %"),
                sub=sub_text,
                sparkline_vals=spk,
                inverse=is_inv,
                badge_label="EOD" if is_inv else "DELAYED",
                badge_color="amber" if is_inv else "blue",
            )
            st.markdown(card_html, unsafe_allow_html=True)
else:
    ui.empty_state("Index overview currently unavailable — check connection or provider status in Settings.")

st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SECTIONS B & C & SECTOR INTELLIGENCE
# -----------------------------------------------------------------------------
col_regime, col_breadth, col_sectors = st.columns([1.3, 1.2, 1.2])

with col_regime:
    st.markdown("### Market Regime")
    reg = mc["regime"]
    cat = reg.get("category", reg.get("label", "Unknown"))
    score = reg.get("score", 0)
    max_score = reg.get("max_score", 7)

    # Status color
    score_pct = score / max_score if max_score else 0
    if score >= 5:
        reg_color = "#10B981"
        badge_variant = "green"
    elif score >= 3:
        reg_color = "#F59E0B"
        badge_variant = "amber"
    else:
        reg_color = "#F43F5E"
        badge_variant = "red"

    st.markdown(
        f'<div class="term-card">'
        f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
        f'    <span style="font-weight:700;font-size:1.05rem;color:{reg_color};">{cat}</span>'
        f'    {ui.badge(f"Score {score}/{max_score}", badge_variant)}'
        f'  </div>'
        f'  <div style="font-size:0.78rem;color:#94A3B8;margin-top:6px;line-height:1.4;">'
        f'    {reg.get("guidance", "")}'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Regime Rule Verification", expanded=False):
        for name, ok in reg.get("rules", []):
            icon = "🟢" if ok else "🔴"
            st.markdown(f"<span style='font-size:0.82rem;'>{icon} {name}</span>", unsafe_allow_html=True)

with col_breadth:
    st.markdown("### Market Breadth")
    b = mc.get("breadth", {})
    if b.get("stocks"):
        adv = b.get("advancers", 0)
        dec = b.get("decliners", 0)
        total_ad = adv + dec if (adv + dec) > 0 else 1
        adv_pct = round(adv / total_ad * 100, 1)

        b_card = (
            f'<div class="term-card">'
            f'  <div class="term-card-header">'
            f'    <span class="term-label">Universe Advancers vs Decliners</span>'
            f'    <span style="font-size:0.75rem;font-family:\'JetBrains Mono\';color:#CBD5E1;">{adv}▲ / {dec}▼ ({adv_pct}%)</span>'
            f'  </div>'
            f'  <div style="height:6px;width:100%;background:#1E293B;border-radius:3px;overflow:hidden;margin-bottom:8px;">'
            f'    <div style="width:{adv_pct}%;height:100%;background:#10B981;"></div>'
            f'  </div>'
            f'  <div style="display:flex;justify-content:space-between;font-size:0.76rem;color:#94A3B8;font-family:\'JetBrains Mono\';">'
            f'    <span>>20 DMA: <strong style="color:#F1F5F9;">{b.get("pct_above_20dma", "—")}%</strong></span>'
            f'    <span>>50 DMA: <strong style="color:#F1F5F9;">{b.get("pct_above_50dma", "—")}%</strong></span>'
            f'    <span>>200 DMA: <strong style="color:#F1F5F9;">{b.get("pct_above_200dma", "—")}%</strong></span>'
            f'  </div>'
            f'  <div style="display:flex;justify-content:space-between;font-size:0.74rem;color:#64748B;margin-top:6px;">'
            f'    <span>New 52W Highs: <strong style="color:#10B981;">{b.get("new_52w_highs", 0)}</strong></span>'
            f'    <span>New 52W Lows: <strong style="color:#F43F5E;">{b.get("new_52w_lows", 0)}</strong></span>'
            f'  </div>'
            f'</div>'
        )
        st.markdown(b_card, unsafe_allow_html=True)
        st.caption(b.get("note", ""))
    else:
        ui.empty_state("Universe breadth data unavailable.")

with col_sectors:
    st.markdown("### Sector Momentum (3M RS)")
    sec = mc.get("sectors", pd.DataFrame())
    if not sec.empty:
        top_sec = sec.iloc[0]
        bot_sec = sec.iloc[-1]
        st.markdown(
            f'<div class="term-card">'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
            f'    <span class="term-label">Leader</span>'
            f'    <span class="term-delta-pos">{top_sec.get("RS vs SPY 3M (pp)", 0):+.1f} pp</span>'
            f'  </div>'
            f'  <div style="font-weight:600;font-size:0.92rem;color:#F1F5F9;">{top_sec["Name"]} ({top_sec["Symbol"]})</div>'
            f'  <div style="border-top:1px solid #1E293B;margin:6px 0;"></div>'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
            f'    <span class="term-label">Laggard</span>'
            f'    <span class="term-delta-neg">{bot_sec.get("RS vs SPY 3M (pp)", 0):+.1f} pp</span>'
            f'  </div>'
            f'  <div style="font-weight:600;font-size:0.92rem;color:#F1F5F9;">{bot_sec["Name"]} ({bot_sec["Symbol"]})</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        ui.freshness_badge(mc.get("sector_data_meta"), "Sectors")
    else:
        ui.empty_state("Sector performance data unavailable.")

st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SECTION E: Prominent AI Market Intelligence Briefing
# -----------------------------------------------------------------------------
st.markdown("### AI Market Intelligence Briefing")

ai_payload = {
    "regime": mc["regime"],
    "indices": mc["indices"],
    "sectors": mc["sectors"],
    "breadth": mc["breadth"],
    "upcoming_events": mc.get("upcoming_events"),
}


def _run_market_briefing():
    # Pass structured data to Gemini
    return gemini.market_analysis(ai_payload)


ui.gemini_panel(
    "overview_briefing",
    "Generate Daily AI Market Briefing",
    _run_market_briefing,
    help_text="Generates an evidence-based market brief with drivers, sector rotation, catalysts, and swing opportunities.",
)

st.markdown('<div style="margin-top:18px;"></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SECTION F: Trading Opportunities & Active Execution
# -----------------------------------------------------------------------------
st.markdown("### Qualified Swing Trade Opportunities")
scan, run_at, as_of = latest_scan()

if run_at is None:
    ui.empty_state("No scan has been run yet. Launch a scan on the Stock Scanner page.")
elif scan.empty:
    ui.empty_state(f"Last scan ({run_at:%Y-%m-%d %H:%M} UTC, as of {as_of}) yielded 0 qualifying setups. Cash is a valid position.")
else:
    st.caption(f"Scan generated at {run_at:%Y-%m-%d %H:%M} UTC · Data as of {as_of} · Deterministic rule criteria")
    view_cols = ["Ticker", "Company", "Sector", "Price", "Score", "Setup", "RSI", "Rel vol", "Earnings flag"]
    avail_cols = [c for c in view_cols if c in scan.columns]
    st.dataframe(scan.head(10)[avail_cols], hide_index=True, width="stretch")

    col_pick, col_btn = st.columns([3, 1])
    with col_pick:
        pick = st.selectbox("Inspect Setup in Technical Analysis", [""] + list(scan.head(10)["Ticker"]), key="_ov_pick")
    with col_btn:
        if pick and st.button("Open Technical Chart →", width="stretch"):
            select_ticker(pick)
            st.switch_page("views/technical.py")

st.markdown('<div style="margin-top:18px;"></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# SECTION D: Today's Market Intelligence Feed
# -----------------------------------------------------------------------------
st.markdown("### Today's Market Intelligence & Catalysts")

feed = query_news(days=2, limit=15)
if feed.empty:
    ui.empty_state("No recent news items in database. Check News & Geopolitics page to sync feeds.")
else:
    for _, item in feed.head(6).iterrows():
        cat = html.escape((item.get("category") or "markets").upper())
        sec = html.escape(item.get("sector") or "")
        pub = item.get("published_utc")
        pub_str = pub.strftime("%b %d %H:%M UTC") if isinstance(pub, datetime) else str(pub)
        link = html.escape(item.get("url") or "#", quote=True)

        st.markdown(
            f'<div class="term-card" style="margin-bottom:6px;">'
            f'  <div style="display:flex;justify-content:space-between;align-items:center;">'
            f'    <div>'
            f'      {ui.badge(cat, "blue")}'
            f'      {ui.badge(sec, "purple") if sec else ""}'
            f'      <span style="font-size:0.72rem;color:#64748B;">{html.escape(item.get("source") or "News")} · {pub_str}</span>'
            f'    </div>'
            f'    <a href="{link}" target="_blank" style="color:#38BDF8;font-size:0.75rem;text-decoration:none;">Source ↗</a>'
            f'  </div>'
            f'  <div style="font-weight:600;font-size:0.88rem;color:#F1F5F9;margin-top:5px;">'
            f'    {html.escape(item.get("headline") or "")}'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
ui.disclaimer()
