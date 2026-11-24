"""Plotly chart builders (institutional dark terminal style)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tradingos.analysis import indicators as ind

BG = "#080B10"
PANEL_BG = "#0B0F17"
GRID = "#141C2A"
TXT = "#94A3B8"
UP = "#10B981"
DOWN = "#F43F5E"
MA_COLORS = {20: "#38BDF8", 50: "#F59E0B", 100: "#A855F7", 200: "#EF4444"}


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=BG,
        plot_bgcolor=PANEL_BG,
        height=height,
        margin=dict(l=12, r=12, t=32, b=12),
        font=dict(family="Inter, -apple-system, sans-serif", color=TXT, size=11),
        legend=dict(
            orientation="h",
            y=1.03,
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(family="JetBrains Mono, monospace", size=10, color="#CBD5E1"),
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#0E1726",
            bordercolor="#1E293B",
            font=dict(family="JetBrains Mono, monospace", size=11, color="#F8FAFC"),
        ),
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(
        gridcolor=GRID,
        gridwidth=1,
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikecolor="#38BDF844",
        tickfont=dict(family="JetBrains Mono, monospace", size=10, color=TXT),
    )
    fig.update_yaxes(
        gridcolor=GRID,
        gridwidth=1,
        side="right",
        tickfont=dict(family="JetBrains Mono, monospace", size=10, color=TXT),
    )
    return fig


def price_chart(
    df: pd.DataFrame,
    snap: dict | None = None,
    mas=(20, 50, 100, 200),
    show_levels: bool = True,
    show_bb: bool = True,
    plan: dict | None = None,
    title: str = "",
    bars: int = 180,
    ma_label: str = "DMA",
) -> go.Figure:
    d = ind.add_all(df)
    d = d.tail(bars)

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.015,
        row_heights=[0.58, 0.14, 0.14, 0.14],
    )

    # Bollinger bands
    if show_bb and "BB_upper" in d and "BB_lower" in d and d["BB_upper"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=d.index,
                y=d["BB_upper"],
                name="BB Upper",
                line=dict(color="rgba(56, 189, 248, 0.25)", width=1, dash="dot"),
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=d.index,
                y=d["BB_lower"],
                name="BB Lower",
                line=dict(color="rgba(56, 189, 248, 0.25)", width=1, dash="dot"),
                fill="tonexty",
                fillcolor="rgba(56, 189, 248, 0.03)",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=d.index,
            open=d["Open"],
            high=d["High"],
            low=d["Low"],
            close=d["Close"],
            increasing_line_color=UP,
            decreasing_line_color=DOWN,
            increasing_fillcolor=UP,
            decreasing_fillcolor=DOWN,
            name="Price",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # Moving averages
    for n in mas:
        col = f"SMA{n}"
        if col in d and d[col].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=d.index,
                    y=d[col],
                    name=f"{n} {ma_label}",
                    line=dict(width=1.3, color=MA_COLORS.get(n, "#CBD5E1")),
                ),
                row=1,
                col=1,
            )

    # Key Support & Resistance Levels
    if show_levels and snap and "supports" in snap:
        for lv in snap["supports"]:
            fig.add_hline(
                y=lv["price"],
                line=dict(color=UP, width=1, dash="dot"),
                row=1,
                col=1,
                annotation_text=f"S {lv['price']:.2f} ({lv['touches']}x)",
                annotation_position="bottom left",
                annotation_font=dict(color=UP, size=10, family="JetBrains Mono, monospace"),
            )
        for lv in snap["resistances"]:
            fig.add_hline(
                y=lv["price"],
                line=dict(color=DOWN, width=1, dash="dot"),
                row=1,
                col=1,
                annotation_text=f"R {lv['price']:.2f} ({lv['touches']}x)",
                annotation_position="top left",
                annotation_font=dict(color=DOWN, size=10, family="JetBrains Mono, monospace"),
            )

    # Trade plan levels
    if plan:
        for key, color, lbl in (
            ("entry", "#38BDF8", "Entry"),
            ("stop", DOWN, "Stop"),
            ("target1", UP, "T1"),
            ("target2", "#059669", "T2"),
        ):
            if plan.get(key):
                fig.add_hline(
                    y=plan[key],
                    line=dict(color=color, width=1.8),
                    row=1,
                    col=1,
                    annotation_text=f"{lbl} {plan[key]:.2f}",
                    annotation_position="right",
                    annotation_font=dict(color=color, size=11, family="JetBrains Mono, monospace"),
                )

    # Volume Subplot
    vol_colors = [UP if c >= o else DOWN for c, o in zip(d["Close"], d["Open"])]
    fig.add_trace(
        go.Bar(
            x=d.index,
            y=d["Volume"],
            marker_color=vol_colors,
            name="Volume",
            showlegend=False,
            opacity=0.75,
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=d.index,
            y=d["Volume"].rolling(20).mean(),
            name="Vol 20MA",
            line=dict(color="#94A3B8", width=1.1),
        ),
        row=2,
        col=1,
    )

    # RSI Subplot
    fig.add_trace(
        go.Scatter(
            x=d.index,
            y=d["RSI14"],
            name="RSI 14",
            line=dict(color="#A855F7", width=1.3),
        ),
        row=3,
        col=1,
    )
    for y, line_color in ((30, "#10B981"), (70, "#F43F5E")):
        fig.add_hline(
            y=y,
            line=dict(color=line_color, width=1, dash="dash"),
            row=3,
            col=1,
            annotation_text=str(y),
            annotation_position="right",
            annotation_font=dict(color=line_color, size=9),
        )

    # MACD Subplot
    fig.add_trace(
        go.Bar(
            x=d.index,
            y=d["MACD_hist"],
            name="MACD hist",
            showlegend=False,
            marker_color=[UP if v >= 0 else DOWN for v in d["MACD_hist"].fillna(0)],
            opacity=0.8,
        ),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=d.index, y=d["MACD"], name="MACD", line=dict(color="#38BDF8", width=1.2)),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=d.index, y=d["MACD_signal"], name="Signal", line=dict(color="#F59E0B", width=1.1)),
        row=4,
        col=1,
    )

    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])] if ma_label == "DMA" else [])
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(family="Inter, sans-serif", size=13, color="#F1F5F9")))
    return _layout(fig, 760)


def rs_chart(close: pd.Series, bench: pd.Series, bars: int = 250, label: str = "vs SPY") -> go.Figure:
    line = ind.rs_line(close.tail(bars), bench)
    fig = go.Figure(go.Scatter(x=line.index, y=line, line=dict(color="#38BDF8", width=1.5), name=f"RS {label}"))
    fig.add_hline(y=100, line=dict(color="#1E293B", dash="dash"))
    fig.update_layout(title=dict(text=f"Relative Strength {label} (Rebased = 100)", x=0.01, font=dict(size=12)))
    return _layout(fig, 260)


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str, height: int = 340) -> go.Figure:
    d = df.dropna(subset=[y]).sort_values(y)
    fig = go.Figure(
        go.Bar(
            x=d[y],
            y=d[x],
            orientation="h",
            marker_color=[UP if v >= 0 else DOWN for v in d[y]],
            text=[f"{v:+.1f}" for v in d[y]],
            textposition="outside",
            textfont=dict(family="JetBrains Mono, monospace", size=10),
        )
    )
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=12)), showlegend=False)
    return _layout(fig, height)


def line_chart(series: dict[str, pd.Series], title: str, height: int = 300, yfmt: str | None = None) -> go.Figure:
    fig = go.Figure()
    palette = ["#38BDF8", "#10B981", "#F59E0B", "#A855F7"]
    for i, (name, s) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, line=dict(width=1.6, color=palette[i % 4])))
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=12)))
    if yfmt:
        fig.update_yaxes(tickformat=yfmt)
    return _layout(fig, height)


def drawdown_chart(dd: pd.Series) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            x=dd.index,
            y=dd.values,
            fill="tozeroy",
            line=dict(color=DOWN, width=1.2),
            fillcolor="rgba(244, 63, 94, 0.15)",
            name="Drawdown %",
        )
    )
    fig.update_layout(title=dict(text="Portfolio Drawdown (%)", x=0.01, font=dict(size=12)))
    return _layout(fig, 220)
