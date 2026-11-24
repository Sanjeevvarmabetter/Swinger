"""Broker statement CSV importer (Vested, DriveWealth, and generic formats).

Parses trade confirmations and account activity CSVs, normalises them into fills,
validates quantities, prices and dates, and integrates them with the journal.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import selectinload

from tradingos.db.models import Fill, Trade, utcnow
from tradingos.db.session import session_scope
from tradingos.journal import service as js
from tradingos.settings import TradingSettings


@dataclass
class ParsedFill:
    ticker: str
    side: str  # BUY | SELL
    filled_at: datetime
    qty: float
    price: float
    commission: float = 0.0
    fx_cost: float = 0.0
    other_costs: float = 0.0
    setup: str = "Broker import"
    note: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "filled_at": self.filled_at.strftime("%Y-%m-%d %H:%M") if self.filled_at else "",
            "qty": self.qty,
            "price": self.price,
            "value": round(self.qty * self.price, 2) if self.qty and self.price else 0.0,
            "commission": self.commission,
            "fx_cost": self.fx_cost,
            "other_costs": self.other_costs,
            "note": self.note,
            "error": self.error,
        }


def _clean_str(val: Any) -> str:
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


def _clean_num(val: Any, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("$", "").replace(",", "").replace("₹", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _parse_date(val: Any) -> datetime | None:
    if val is None or pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, time(16, 0))
    s = str(val).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%b %d, %Y",
        "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.time() == time(0, 0):
                dt = datetime.combine(dt.date(), time(16, 0))
            return dt
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(s)
        if pd.notna(ts):
            dt = ts.to_pydatetime()
            if dt.time() == time(0, 0):
                dt = datetime.combine(dt.date(), time(16, 0))
            return dt
    except Exception:
        pass
    return None


def _normalize_side(val: Any) -> str:
    s = _clean_str(val).upper()
    if s in ("BUY", "B", "BOUGHT", "PURCHASE"):
        return "BUY"
    if s in ("SELL", "S", "SOLD", "SALE"):
        return "SELL"
    return s


def parse_trades_csv(csv_content: str | bytes | io.StringIO) -> tuple[list[ParsedFill], list[str]]:
    """Parse CSV text/file into a list of ParsedFill objects and a list of warnings."""
    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode("utf-8-sig", errors="replace")
    if isinstance(csv_content, str):
        csv_file = io.StringIO(csv_content)
    else:
        csv_file = csv_content

    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        return [], [f"Failed to parse CSV: {e}"]

    if df.empty:
        return [], ["CSV file is empty."]

    # Normalise column headers
    cols = {c: re.sub(r"[\s_\-]+", "_", str(c).strip().lower()) for c in df.columns}
    df = df.rename(columns=cols)

    # Column mapping aliases
    ticker_col = next((c for c in df.columns if c in ("ticker", "symbol", "stock", "instrument", "security")), None)
    side_col = next((c for c in df.columns if c in ("side", "type", "action", "transaction_type", "order_type", "activity_type")), None)
    date_col = next((c for c in df.columns if c in ("date", "filled_at", "fill_date", "trade_date", "transaction_date", "execution_time")), None)
    qty_col = next((c for c in df.columns if c in ("qty", "quantity", "shares", "filled_qty", "units")), None)
    price_col = next((c for c in df.columns if c in ("price", "fill_price", "execution_price", "share_price", "avg_price")), None)
    comm_col = next((c for c in df.columns if c in ("commission", "fee", "fees", "commission_usd", "brokerage")), None)
    fx_col = next((c for c in df.columns if c in ("fx_cost", "fx_fee", "fx_markup")), None)
    other_col = next((c for c in df.columns if c in ("other_costs", "other_fees", "sec_fee", "taf_fee", "tax")), None)
    note_col = next((c for c in df.columns if c in ("note", "notes", "description", "memo")), None)

    if not ticker_col or not side_col or not date_col or not qty_col or not price_col:
        missing = []
        if not ticker_col: missing.append("ticker/symbol")
        if not side_col: missing.append("side/type")
        if not date_col: missing.append("date/trade_date")
        if not qty_col: missing.append("quantity/shares")
        if not price_col: missing.append("price/share_price")
        return [], [f"Missing required columns in CSV: {', '.join(missing)}. "
                    "Expected headers: ticker, side, date, qty, price (commissions/fees optional)."]

    parsed: list[ParsedFill] = []
    warnings: list[str] = []

    for idx, row in df.iterrows():
        raw_ticker = _clean_str(row[ticker_col]).upper()
        # Clean ticker e.g. "AAPL US", "NASDAQ:AAPL" -> "AAPL"
        ticker = re.sub(r"^(NASDAQ:|NYSE:|AMEX:)", "", raw_ticker).split()[0] if raw_ticker else ""
        side = _normalize_side(row[side_col])
        filled_at = _parse_date(row[date_col])
        qty = _clean_num(row[qty_col])
        price = _clean_num(row[price_col])
        comm = abs(_clean_num(row[comm_col])) if comm_col else 0.0
        fx = abs(_clean_num(row[fx_col])) if fx_col else 0.0
        other = abs(_clean_num(row[other_col])) if other_col else 0.0
        note = _clean_str(row[note_col]) if note_col else ""

        error = None
        if not ticker or not ticker.replace("-", "").replace(".", "").isalnum():
            error = f"Row {idx + 1}: Invalid ticker '{raw_ticker}'"
        elif side not in ("BUY", "SELL"):
            error = f"Row {idx + 1}: Unrecognized side '{row[side_col]}' (expected BUY or SELL)"
        elif filled_at is None:
            error = f"Row {idx + 1}: Invalid date format '{row[date_col]}'"
        elif qty <= 0:
            error = f"Row {idx + 1}: Quantity must be positive (got {qty})"
        elif price <= 0:
            error = f"Row {idx + 1}: Price must be positive (got {price})"

        parsed.append(ParsedFill(
            ticker=ticker,
            side=side,
            filled_at=filled_at or utcnow(),
            qty=qty,
            price=price,
            commission=comm,
            fx_cost=fx,
            other_costs=other,
            note=note,
            error=error,
        ))

    return parsed, warnings


def generate_template_csv() -> str:
    """Generate a clean CSV template for trade statements."""
    return (
        "ticker,side,date,qty,price,commission,fx_cost,other_costs,notes\n"
        "AAPL,BUY,2026-11-01 16:00,10,225.50,0.00,0.00,0.02,Breakout entry\n"
        "AAPL,SELL,2026-11-15 16:00,5,238.00,0.00,0.00,0.02,Target 1 profit booking\n"
        "MSFT,BUY,2026-11-05 16:00,5,415.20,0.00,0.00,0.02,Pullback to 20DMA\n"
    )


def execute_import(
    fills: list[ParsedFill],
    cfg: TradingSettings,
    engine: Engine | None = None,
) -> dict[str, Any]:
    """Execute the import of valid fills into the database.

    Pairs BUYs and SELLs with existing trades or opens new trades.
    Returns summary stats of imported trades, fills, and any errors.
    """
    valid = [f for f in fills if not f.error]
    if not valid:
        return {"imported_fills": 0, "new_trades": 0, "exits_recorded": 0, "errors": ["No valid fills to import."]}

    # Sort fills chronologically
    valid = sorted(valid, key=lambda f: f.filled_at)

    new_trades_count = 0
    exits_count = 0
    imported_fills_count = 0
    errors: list[str] = []

    with session_scope(engine) as s:
        acct = js.account_state(cfg, engine=engine)
        equity = js.sizing_equity(acct)

        for f in valid:
            if f.side == "BUY":
                # Check if there is already an open trade for this ticker
                existing = s.scalars(
                    select(Trade)
                    .options(selectinload(Trade.fills))
                    .where(Trade.ticker == f.ticker, Trade.status == "OPEN")
                ).first()

                if existing:
                    # Append fill to the existing trade
                    existing.fills.append(
                        Fill(
                            side="BUY",
                            filled_at=f.filled_at,
                            qty=f.qty,
                            price=f.price,
                            commission=f.commission,
                            fx_cost=f.fx_cost,
                            other_costs=f.other_costs,
                            note=f.note or "Imported fill",
                        )
                    )
                    imported_fills_count += 1
                else:
                    # Open a new trade
                    # Initial stop placed 7% below entry if not specified
                    initial_stop = round(f.price * 0.93, 2)
                    t = Trade(
                        ticker=f.ticker,
                        sector="",
                        setup=f.setup or "Broker import",
                        entry_thesis=f.note or "Imported from broker statement",
                        planned_entry=f.price,
                        initial_stop=initial_stop,
                        initial_target=round(f.price * 1.15, 2),
                        planned_risk_pct=cfg.risk_per_trade_pct,
                        equity_at_entry=equity,
                        current_stop=initial_stop,
                        status="OPEN",
                    )
                    t.fills.append(
                        Fill(
                            side="BUY",
                            filled_at=f.filled_at,
                            qty=f.qty,
                            price=f.price,
                            commission=f.commission,
                            fx_cost=f.fx_cost,
                            other_costs=f.other_costs,
                            note=f.note or "Imported entry fill",
                        )
                    )
                    s.add(t)
                    s.flush()
                    new_trades_count += 1
                    imported_fills_count += 1

            elif f.side == "SELL":
                # Find the open trade for this ticker
                trade = s.scalars(
                    select(Trade)
                    .options(selectinload(Trade.fills))
                    .where(Trade.ticker == f.ticker, Trade.status == "OPEN")
                ).first()

                if not trade:
                    errors.append(f"Cannot record SELL for {f.ticker}: No open trade found for this ticker.")
                    continue

                m = js.compute_metrics(trade)
                sell_qty = min(f.qty, m.open_qty) if m.open_qty > 0 else f.qty
                if sell_qty <= 0:
                    errors.append(f"Cannot record SELL for {f.ticker}: Trade already fully closed.")
                    continue

                trade.fills.append(
                    Fill(
                        side="SELL",
                        filled_at=f.filled_at,
                        qty=sell_qty,
                        price=f.price,
                        commission=f.commission,
                        fx_cost=f.fx_cost,
                        other_costs=f.other_costs,
                        note=f.note or "Imported exit fill",
                    )
                )
                s.flush()
                m_after = js.compute_metrics(trade)
                if m_after.open_qty <= 1e-9:
                    trade.status = "CLOSED"
                    trade.closed_at = f.filled_at
                    trade.exit_reason = (trade.exit_reason + "\n" if trade.exit_reason else "") + \
                        f"[{f.filled_at:%Y-%m-%d}] Closed via broker import @ {f.price:.2f}"
                exits_count += 1
                imported_fills_count += 1

    return {
        "imported_fills": imported_fills_count,
        "new_trades": new_trades_count,
        "exits_recorded": exits_count,
        "errors": errors,
    }
