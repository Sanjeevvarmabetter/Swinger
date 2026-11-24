"""Global Trends Radar — evidence-based theme stages (price momentum + news attention)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tradingos.ai import gemini
from tradingos.intel import trends
from tradingos.intel.news_rank import rank_news
from tradingos.ui import charts
from tradingos.ui import components as ui
from tradingos.ui import intel_ui as iu

ui.render_top_bar(show_refresh=False)
iu.page_header("Global Trends Radar", "Which investment themes are emerging, accelerating, established, crowded or "
               "fading — classified by fixed rules over relative strength, trend, extension, breadth and news attention")

with st.spinner("Computing theme baskets…"):
    tab, detail, meta = iu.radar()
iu.meta_line({**meta, "missing": [m for m in meta.get("missing", []) if "last bar" not in m]})

STAGE_COLOR = {"Emerging": "#22D3EE", "Gaining momentum": "#2FBF71", "Established": "#4EA8F2", "Crowded": "#E9A23B",
               "Weakening": "#FB923C", "Out of favour": "#EF5B67", "No clear trend": "#64748B"}

t_over, t_theme, t_method = st.tabs(["Radar", "Theme deep-dive", "Methodology"])

with t_over:
    groups = st.multiselect("Groups", sorted(tab["Group"].unique()), default=sorted(tab["Group"].unique()))
    d = tab[tab["Group"].isin(groups)]
    counts = d["Stage"].value_counts()
    st.markdown(" ".join(f'<span class="tos-chip" style="border-color:{STAGE_COLOR[s]};color:{STAGE_COLOR[s]}">'
                         f'{s}: {counts.get(s, 0)}</span>' for s in trends.STAGES), unsafe_allow_html=True)
    ok = d.dropna(subset=["RS 3M (pp)", "RS 1M (pp)"])
    fig = go.Figure()
    for stage, g in ok.groupby("Stage"):
        fig.add_trace(go.Scatter(
            x=g["RS 3M (pp)"], y=g["RS 1M (pp)"], mode="markers+text", name=stage, text=g["Theme"],
            textposition="top center", textfont=dict(size=9, color="#CBD5E1"),
            marker=dict(size=[10 + min(n, 80) ** 0.6 * 2 for n in g["News 7d"]], color=STAGE_COLOR[stage], opacity=0.85,
                        line=dict(width=0.5, color="#0B0F17")),
            customdata=g[["Group", "RS 6M (pp)", "vs 200DMA %", "News 7d"]].values,
            hovertemplate="<b>%{text}</b> (%{customdata[0]})<br>RS 3M %{x:+.1f}pp · RS 1M %{y:+.1f}pp · "
                          "RS 6M %{customdata[1]:+.1f}pp<br>vs 200DMA %{customdata[2]:+.1f}% · news 7d %{customdata[3]}"
                          "<extra></extra>"))
    fig.add_hline(y=0, line=dict(color="#334155", dash="dot"))
    fig.add_vline(x=0, line=dict(color="#334155", dash="dot"))
    for x, y, txt in ((1, 1, "Leading & accelerating"), (-1, 1, "Improving"), (-1, -1, "Lagging"), (1, -1, "Leading but fading")):
        fig.add_annotation(xref="paper", yref="paper", x=0.5 + x * 0.47, y=0.5 + y * 0.47, text=txt, showarrow=False,
                           font=dict(size=10, color="#475569"), xanchor="right" if x > 0 else "left")
    fig.update_layout(title=dict(text="Momentum map — x: 3-month RS vs benchmark, y: 1-month RS (pp); size: news stories 7d",
                                 x=0.01, font=dict(size=12)), hovermode="closest")
    fig = charts._layout(fig, 560)
    fig.update_xaxes(title_text="RS 3M (pp)", showspikes=False)
    fig.update_yaxes(title_text="RS 1M (pp)", showspikes=False, side="left")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(d.drop(columns=["Basket"]).sort_values(["Stage", "RS 3M (pp)"], ascending=[True, False]),
                 hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in
                                ("RS 1M (pp)", "RS 3M (pp)", "RS 6M (pp)", "Return 3M %", "vs 200DMA %")})
    st.caption("US themes are measured against the S&P 500, Indian themes against the Nifty 50. RS = theme basket "
               "return minus benchmark return. News attention compares the last 7 days with the prior 28-day weekly "
               "average once enough history has been collected.")

with t_theme:
    name = st.selectbox("Theme", tab.sort_values("Group")["Theme"].tolist())
    det = detail[name]
    t, m, a = det["theme"], det["metrics"], det["attention"]
    st.markdown(f'### {name} <span class="tos-chip" style="border-color:{STAGE_COLOR[det["stage"]]};'
                f'color:{STAGE_COLOR[det["stage"]]}">{det["stage"]}</span>', unsafe_allow_html=True)
    st.caption(f"Evidence: {det['why']} · basket = {m.get('basket_basis')}: {', '.join(m.get('basket_members', []))} · "
               f"benchmark {t['benchmark']} · data as of {m.get('as_of')}")
    if m.get("error"):
        st.warning(m["error"])
    else:
        cols = st.columns(6)
        cols[0].metric("Return 3M", ui.pct(m.get("ret_3M")))
        cols[1].metric("RS 1M / 3M", f"{ui.pct(m.get('rs_1M'))} / {ui.pct(m.get('rs_3M'))}")
        cols[2].metric("RS 6M", ui.pct(m.get("rs_6M")))
        cols[3].metric("vs 200DMA", ui.pct(m.get("pct_from_200dma")))
        cols[4].metric("RSI(14)", m.get("rsi14"))
        cols[5].metric("Companies >50DMA", f"{m.get('breadth_above_50dma_pct', '—')}%")
        idx, bench = m["series"], m["bench_series"]
        win = idx.index[-1] - pd.Timedelta(days=365)
        i1, b1 = idx[idx.index >= win], bench[bench.index >= win]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=i1.index, y=(i1 / i1.iloc[0] - 1) * 100, name=f"{name} basket",
                                 line=dict(color="#2FBF71", width=1.8)))
        fig.add_trace(go.Scatter(x=b1.index, y=(b1 / b1.iloc[0] - 1) * 100, name=t["benchmark"],
                                 line=dict(color="#94A3B8", width=1.2)))
        fig.update_layout(title=dict(text="1-year performance vs benchmark (%)", x=0.01, font=dict(size=12)))
        st.plotly_chart(charts._layout(fig, 320), width="stretch")
    with st.container(border=True):
        st.markdown("**Framework** _(static analysis — not a recommendation)_")
        st.markdown(f"- **Representative companies:** {', '.join(t['companies']) or '—'}\n"
                    f"- **Potential beneficiaries:** {t['beneficiaries']}\n- **Potential losers:** {t['losers'] or '—'}\n"
                    f"- **Risks:** {t['risks']}\n- **What would invalidate the trend:** {t['invalidation']}\n"
                    f"- **Related indicators:** {', '.join(t['indicators'])}")
    df_snap, _ = iu.snapshot()
    from tradingos.intel.markets import row
    ind_rows = [row(df_snap, s) for s in t["indicators"]]
    ind_rows = [{"Indicator": r["Name"], "Last": r["Last"], "1W %": r["1W %"], "1M %": r["1M %"], "Last bar": r["Last bar"]}
                for r in ind_rows if r]
    if ind_rows:
        st.markdown("**Related market indicators**")
        st.dataframe(ui.color_pct_cols(pd.DataFrame(ind_rows), ["1W %", "1M %"]), hide_index=True, width="stretch")
    st.markdown(f"**Relevant news** — {a['stories_7d']} stories in 7 days"
                + (f" · attention ratio {a['attention_ratio']}" if a.get("attention_ratio") else
                   " · attention ratio withheld until ~35 days of news have been collected")
                + (f" · tone {a['pos_share']}% positive / {a['neg_share']}% negative (headline keyword heuristic)"
                   if a.get("pos_share") is not None else ""))
    matches = a.get("matches")
    ranked = rank_news(matches[pd.to_datetime(matches["published_utc"]) >= pd.Timestamp(iu.utc_now_str()[:16]) - pd.Timedelta(days=14)]) \
        if matches is not None and len(matches) else pd.DataFrame()
    iu.story_list(ranked, n=10, tiers=("MUST KNOW", "IMPORTANT", "INTERESTING", "IGNORE FOR NOW"),
                  empty="No matching stories in the last 14 days.")
    payload = {"theme": t, "stage": det["stage"], "stage_evidence": det["why"],
               "metrics": {k: v for k, v in m.items() if k not in ("series", "bench_series")},
               "attention": {k: v for k, v in a.items() if k != "matches"},
               "related_indicators": ind_rows,
               "news": ranked.head(15)[["tier", "headline", "source", "published_utc", "url", "info_type"]] if len(ranked) else [],
               "methodology": trends.METHODOLOGY}
    ui.gemini_panel(f"trend_{name}", f"Analyse {name}", lambda: gemini.intel_analysis("trends_analyst", payload, name),
                    payload_for_links=payload)

with t_method:
    st.markdown("Stages are checked **in this order**; the first rule that matches wins.")
    st.table(pd.DataFrame(trends.METHODOLOGY, columns=["Stage", "Rule"]))
    st.markdown("- **Basket:** equal-weight index of the theme's ETF/index proxies (or its companies when no proxy "
                "has data), daily rebalanced.\n- **RS:** basket return minus benchmark return over 21/63/126 trading days."
                "\n- **Attention ratio:** theme-keyword stories in the last 7 days ÷ weekly average of the previous 28 days."
                "\n- **Edit themes, keywords, proxies and companies** in `config/themes.json`.\n"
                "- Limitations: price-based stages lag turning points; keyword attention counts mentions, not "
                "importance; ETF proxies imperfectly represent a theme.")

ui.disclaimer()
