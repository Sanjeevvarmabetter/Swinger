"""Watchlist + price alerts."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from tradingos.analysis import indicators as ind
from tradingos.analysis.technical import classify_trend
from tradingos.data.providers import get_market_provider
from tradingos.db.models import Alert, WatchlistItem
from tradingos.db.session import session_scope


def add(ticker: str, notes: str = "", tags: str = "", alert_above: float | None = None,
        alert_below: float | None = None) -> None:
    t = ticker.strip().upper()
    if not t:
        raise ValueError("Ticker required")
    with session_scope() as s:
        existing = s.scalars(select(WatchlistItem).where(WatchlistItem.ticker == t)).first()
        if existing:
            existing.notes, existing.tags = notes or existing.notes, tags or existing.tags
            existing.alert_above, existing.alert_below = alert_above, alert_below
        else:
            s.add(WatchlistItem(ticker=t, notes=notes, tags=tags, alert_above=alert_above, alert_below=alert_below))


def remove(ticker: str) -> None:
    with session_scope() as s:
        for w in s.scalars(select(WatchlistItem).where(WatchlistItem.ticker == ticker.upper())).all():
            s.delete(w)


def items() -> list[WatchlistItem]:
    with session_scope() as s:
        return list(s.scalars(select(WatchlistItem).order_by(WatchlistItem.ticker)).all())


def watchlist_snapshot() -> pd.DataFrame:
    its = items()
    cols = ["Ticker", "Notes", "Tags", "Alert above", "Alert below", "Last", "1D %", "1M %", "Trend", "RSI", "As of", "Alert"]
    if not its:
        return pd.DataFrame(columns=cols)
    res = get_market_provider().history([w.ticker for w in its], period="1y")
    rows = []
    for w in its:
        df = (res.data or {}).get(w.ticker)
        row = {"Ticker": w.ticker, "Notes": w.notes, "Tags": w.tags, "Alert above": w.alert_above,
               "Alert below": w.alert_below, "Last": None, "1D %": None, "1M %": None, "Trend": "No data",
               "RSI": None, "As of": None, "Alert": ""}
        if df is not None and len(df) > 30:
            c = df["Close"]
            s20, s50, s200 = (ind.finite(ind.sma(c, n).iloc[-1]) for n in (20, 50, 200))
            last = float(c.iloc[-1])
            row.update({"Last": round(last, 2), "1D %": round(ind.pct_return(c, 1) or 0, 2),
                        "1M %": None if ind.pct_return(c, 21) is None else round(ind.pct_return(c, 21), 2),
                        "Trend": classify_trend(last, s20, s50, s200, ind.slope(ind.sma(c, 50), 10)),
                        "RSI": round(ind.rsi(c).iloc[-1], 1), "As of": df.index[-1].date().isoformat()})
            if w.alert_above and last >= w.alert_above:
                row["Alert"] = f"▲ above {w.alert_above:g}"
            elif w.alert_below and last <= w.alert_below:
                row["Alert"] = f"▼ below {w.alert_below:g}"
        rows.append(row)
    return pd.DataFrame(rows, columns=cols)


def check_alerts() -> list[str]:
    """Evaluate alerts on latest close; store new ones. Used by scripts/check_alerts.py."""
    snap = watchlist_snapshot()
    msgs = []
    if snap.empty:
        return msgs
    with session_scope() as s:
        for _, r in snap[snap["Alert"] != ""].iterrows():
            msg = f"{r['Ticker']} {r['Alert']} (last {r['Last']} as of {r['As of']})"
            dup = s.scalars(select(Alert).where(Alert.message == msg)).first()
            if not dup:
                s.add(Alert(ticker=r["Ticker"], message=msg))
                msgs.append(msg)
    return msgs


def open_alerts() -> list[Alert]:
    with session_scope() as s:
        return list(s.scalars(select(Alert).where(Alert.acknowledged.is_(False)).order_by(Alert.created_at.desc())).all())


def acknowledge(alert_id: int) -> None:
    with session_scope() as s:
        a = s.get(Alert, alert_id)
        if a:
            a.acknowledged = True
