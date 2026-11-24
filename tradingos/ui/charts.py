"""Plotly chart builders (institutional dark terminal style)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


BG = "#0A0D12"
PANEL_BG = "#0D1118"
GRID = "#141C2A"
TXT = "#94A3B8"
UP = "#2FBF71"
DOWN = "#EF5B67"


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=BG,
        plot_bgcolor=PANEL_BG,
        height=height,
        margin=dict(l=8, r=8, t=36, b=8),
        font=dict(family="Inter, -apple-system, sans-serif", color=TXT, size=11),
        legend=dict(
            orientation="h",
            y=-0.12,
            yanchor="top",
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
        spikecolor="#4EA8F244",
        tickfont=dict(family="JetBrains Mono, monospace", size=10, color=TXT),
    )
    fig.update_yaxes(
        gridcolor=GRID,
        gridwidth=1,
        side="right",
        tickfont=dict(family="JetBrains Mono, monospace", size=10, color=TXT),
    )
    return fig


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
    palette = ["#4EA8F2", "#2FBF71", "#E9A23B", "#A855F7"]
    for i, (name, s) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, line=dict(width=1.6, color=palette[i % 4])))
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=12)))
    if yfmt:
        fig.update_yaxes(tickformat=yfmt)
    return _layout(fig, height)
