"""Long-term portfolio (Module 10). Separate database (longterm.db); monitoring/research only.

Nothing in this module is ever imported by the trading-equity calculations.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import requests
from sqlalchemy import select

from tradingos.data import cache
from tradingos.db.models import LongTermHolding
from tradingos.db.session import longterm_engine, session_scope

ASSET_CLASSES = ["US ETF", "US Stock", "Indian Mutual Fund", "Indian Stock", "Gold", "Other"]


def add_holding(asset_class: str, symbol: str, name: str, quantity: float, avg_cost: float, currency: str,
                price_source: str, manual_price: float | None = None, notes: str = "") -> None:
    if asset_class not in ASSET_CLASSES:
        raise ValueError("Unknown asset class")
    if quantity < 0 or avg_cost < 0:
        raise ValueError("Quantity and cost must be non-negative")
    with session_scope(longterm_engine()) as s:
        s.add(LongTermHolding(asset_class=asset_class, symbol=symbol.strip(), name=name.strip(), quantity=quantity,
                              avg_cost=avg_cost, currency=currency, price_source=price_source,
                              manual_price=manual_price, manual_price_date=date.today() if manual_price else None,
                              notes=notes))


def delete_holding(hid: int) -> None:
    with session_scope(longterm_engine()) as s:
        h = s.get(LongTermHolding, hid)
        if h:
            s.delete(h)


def update_manual_price(hid: int, price: float) -> None:
    with session_scope(longterm_engine()) as s:
        h = s.get(LongTermHolding, hid)
        if h:
            h.manual_price, h.manual_price_date = price, date.today()


def holdings() -> list[LongTermHolding]:
    with session_scope(longterm_engine()) as s:
        return list(s.scalars(select(LongTermHolding).order_by(LongTermHolding.asset_class)).all())


def mf_nav(scheme_code: str) -> tuple[float | None, str | None]:
    """Latest NAV from api.mfapi.in (free, public, AMFI data)."""
    try:
        data = cache.cached(f"mfapi|{scheme_code}", 6 * 3600, lambda: requests.get(
            f"https://api.mfapi.in/mf/{scheme_code}/latest", timeout=20).json())
        d = data["data"][0]
        return float(d["nav"]), d["date"]
    except Exception:
        return None, None


def valuation(usd_inr: float | None = None) -> pd.DataFrame:
    from tradingos.data.providers import get_market_provider
    hs = holdings()
    if not hs:
        return pd.DataFrame()
    yf_syms = [h.symbol for h in hs if h.price_source == "yfinance"]
    res = get_market_provider().history(yf_syms, period="5d") if yf_syms else None
    rows = []
    for h in hs:
        price, as_of, src = None, None, h.price_source
        if h.price_source == "yfinance" and res is not None and res.ok and h.symbol.upper() in res.data:
            df = res.data[h.symbol.upper()]
            price, as_of = float(df["Close"].iloc[-1]), df.index[-1].date().isoformat()
        elif h.price_source == "mfapi":
            price, as_of = mf_nav(h.symbol)
        elif h.manual_price:
            price, as_of = h.manual_price, h.manual_price_date.isoformat() if h.manual_price_date else None
        value = price * h.quantity if price is not None else None
        cost = h.avg_cost * h.quantity
        rows.append({"id": h.id, "Asset class": h.asset_class, "Symbol": h.symbol, "Name": h.name,
                     "Qty": h.quantity, "Avg cost": h.avg_cost, "Currency": h.currency, "Price": price,
                     "Price as of": as_of, "Source": src, "Value": value, "Cost": cost,
                     "Gain": (value - cost) if value is not None else None,
                     "Gain %": ((value / cost - 1) * 100) if value is not None and cost else None, "Notes": h.notes})
    df = pd.DataFrame(rows)
    if usd_inr:
        df["Value (INR)"] = df.apply(lambda r: None if r["Value"] is None else
                                     r["Value"] * (usd_inr if r["Currency"] == "USD" else 1), axis=1)
    return df


def usd_inr_rate() -> tuple[float | None, str | None]:
    from tradingos.data.providers import get_market_provider
    r = get_market_provider().history(["INR=X"], period="5d")
    if r.ok and "INR=X" in r.data:
        df = r.data["INR=X"]
        return float(df["Close"].iloc[-1]), df.index[-1].date().isoformat()
    return None, None
