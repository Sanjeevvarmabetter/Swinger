"""Indian Income Tax Capital Gains Helper for US Stocks & ETFs (Schedule CG & Schedule FA).

Calculates FY-wise realized capital gains in INR:
  * Financial Year: April 1 to March 31.
  * Asset classification: Unlisted foreign equities.
  * Holding period: <= 24 months (730 days) -> Short Term Capital Gains (STCG).
                    > 24 months -> Long Term Capital Gains (LTCG).
  * Converts transaction amounts to INR using historical or latest USD/INR exchange rates.
  * Deducts allowable transfer & brokerage expenses.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from tradingos.data.providers import get_market_provider

# Default fallback USD/INR exchange rate if provider has no history for a specific date
DEFAULT_USD_INR = 84.50


def fy_for_date(d: date | datetime) -> str:
    """Return the Indian Financial Year string (e.g. 'FY 2025-26') for a given date."""
    if isinstance(d, datetime):
        d = d.date()
    year = d.year
    if d.month >= 4:
        return f"FY {year}-{str(year + 1)[-2:]}"
    else:
        return f"FY {year - 1}-{str(year)[-2:]}"


def fy_date_range(fy_str: str) -> tuple[date, date]:
    """Parse 'FY 2025-26' into start (2025-04-01) and end (2026-03-31) dates."""
    parts = fy_str.replace("FY", "").strip().split("-")
    start_year = int(parts[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def get_historical_rates() -> pd.Series:
    """Fetch daily USD/INR history from Yahoo Finance ('INR=X')."""
    prov = get_market_provider()
    res = prov.history(["INR=X"], period="5y")
    if res.ok and "INR=X" in res.data:
        df = res.data["INR=X"]
        s = df["Close"].dropna()
        s.index = [pd.Timestamp(i).date() for i in s.index]
        return s
    return pd.Series(dtype=float)


_RATE_CACHE: pd.Series | None = None


def rate_for_date(d: date, rates: pd.Series | None = None) -> float:
    """Find the USD/INR rate on or immediately preceding date `d`."""
    global _RATE_CACHE
    if rates is None:
        if _RATE_CACHE is None or _RATE_CACHE.empty:
            _RATE_CACHE = get_historical_rates()
        rates = _RATE_CACHE

    if rates is not None and not rates.empty:
        # Exact match
        if d in rates.index:
            return float(rates.loc[d])
        # Closest preceding date (weekends / holidays use last business day)
        prior = rates[rates.index <= d]
        if not prior.empty:
            return float(prior.iloc[-1])
        # Or next available date if d is before history
        return float(rates.iloc[0])
    return DEFAULT_USD_INR


@dataclass
class TaxTradeRow:
    trade_id: int
    ticker: str
    qty: float
    entry_date: date
    exit_date: date
    holding_days: int
    gain_type: str  # STCG | LTCG
    buy_px_usd: float
    sell_px_usd: float
    buy_fx: float
    sell_fx: float
    proceeds_usd: float
    cost_usd: float
    fees_usd: float
    proceeds_inr: float
    cost_inr: float
    fees_inr: float
    net_gain_usd: float
    net_gain_inr: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaxReport:
    fy: str
    trades_count: int
    total_proceeds_inr: float
    total_cost_inr: float
    total_fees_inr: float
    net_stcg_inr: float
    net_ltcg_inr: float
    total_taxable_gain_inr: float
    est_slab_tax_inr: float
    rows: list[TaxTradeRow]

    def to_dataframe(self) -> pd.DataFrame:
        if not self.rows:
            return pd.DataFrame()
        records = []
        for r in self.rows:
            records.append({
                "Trade ID": f"#{r.trade_id}",
                "Ticker": r.ticker,
                "Qty": r.qty,
                "Buy Date": r.entry_date.isoformat(),
                "Sell Date": r.exit_date.isoformat(),
                "Holding (Days)": r.holding_days,
                "Type": r.gain_type,
                "Buy Px ($)": round(r.buy_px_usd, 2),
                "Sell Px ($)": round(r.sell_px_usd, 2),
                "Buy Rate (₹)": round(r.buy_fx, 2),
                "Sell Rate (₹)": round(r.sell_fx, 2),
                "Cost (₹)": round(r.cost_inr, 2),
                "Proceeds (₹)": round(r.proceeds_inr, 2),
                "Expenses (₹)": round(r.fees_inr, 2),
                "Net Gain ($)": round(r.net_gain_usd, 2),
                "Net Gain (₹)": round(r.net_gain_inr, 2),
            })
        return pd.DataFrame(records)


def compute_indian_tax_report(
    closed_trades: pd.DataFrame,
    fy: str | None = None,
    fx_override: float | None = None,
    est_slab_rate_pct: float = 30.0,
) -> TaxReport:
    """Generate an Indian Capital Gains Tax report for a given FY or all closed trades."""
    if closed_trades.empty:
        return TaxReport(
            fy=fy or "All",
            trades_count=0,
            total_proceeds_inr=0.0,
            total_cost_inr=0.0,
            total_fees_inr=0.0,
            net_stcg_inr=0.0,
            net_ltcg_inr=0.0,
            total_taxable_gain_inr=0.0,
            est_slab_tax_inr=0.0,
            rows=[],
        )

    rates = None if fx_override else get_historical_rates()
    rows: list[TaxTradeRow] = []

    start_date, end_date = fy_date_range(fy) if fy and fy != "All" else (None, None)

    for _, t in closed_trades.iterrows():
        exit_dt = pd.to_datetime(t.get("exit_date"))
        if pd.isna(exit_dt):
            continue
        exit_d = exit_dt.date()

        if start_date and end_date and not (start_date <= exit_d <= end_date):
            continue

        entry_dt = pd.to_datetime(t.get("entry_date"))
        entry_d = entry_dt.date() if pd.notna(entry_dt) else exit_d

        holding_days = int(t.get("holding_days") or (exit_d - entry_d).days)
        # Foreign shares: <= 730 days (24 months) = STCG; > 730 days = LTCG
        gain_type = "LTCG" if holding_days > 730 else "STCG"

        qty = float(t.get("qty") or 0.0)
        buy_px = float(t.get("avg_entry") or 0.0)
        sell_px = float(t.get("avg_exit") or 0.0)
        fees_usd = float(t.get("fees_total") or 0.0)

        buy_fx = fx_override or rate_for_date(entry_d, rates)
        sell_fx = fx_override or rate_for_date(exit_d, rates)

        proceeds_usd = qty * sell_px
        cost_usd = qty * buy_px
        proceeds_inr = proceeds_usd * sell_fx
        cost_inr = cost_usd * buy_fx
        fees_inr = fees_usd * sell_fx

        net_gain_usd = float(t.get("realized_net") or (proceeds_usd - cost_usd - fees_usd))
        net_gain_inr = proceeds_inr - cost_inr - fees_inr

        rows.append(TaxTradeRow(
            trade_id=int(t["id"]),
            ticker=str(t["ticker"]),
            qty=qty,
            entry_date=entry_d,
            exit_date=exit_d,
            holding_days=holding_days,
            gain_type=gain_type,
            buy_px_usd=buy_px,
            sell_px_usd=sell_px,
            buy_fx=buy_fx,
            sell_fx=sell_fx,
            proceeds_usd=proceeds_usd,
            cost_usd=cost_usd,
            fees_usd=fees_usd,
            proceeds_inr=proceeds_inr,
            cost_inr=cost_inr,
            fees_inr=fees_inr,
            net_gain_usd=net_gain_usd,
            net_gain_inr=net_gain_inr,
        ))

    tot_proceeds = sum(r.proceeds_inr for r in rows)
    tot_cost = sum(r.cost_inr for r in rows)
    tot_fees = sum(r.fees_inr for r in rows)
    stcg = sum(r.net_gain_inr for r in rows if r.gain_type == "STCG")
    ltcg = sum(r.net_gain_inr for r in rows if r.gain_type == "LTCG")
    taxable = max(0.0, stcg) + max(0.0, ltcg)
    est_tax = round(max(0.0, stcg) * est_slab_rate_pct / 100 + max(0.0, ltcg) * 0.125, 2)

    return TaxReport(
        fy=fy or "All",
        trades_count=len(rows),
        total_proceeds_inr=round(tot_proceeds, 2),
        total_cost_inr=round(tot_cost, 2),
        total_fees_inr=round(tot_fees, 2),
        net_stcg_inr=round(stcg, 2),
        net_ltcg_inr=round(ltcg, 2),
        total_taxable_gain_inr=round(taxable, 2),
        est_slab_tax_inr=est_tax,
        rows=rows,
    )
