"""Trading journal (Module 8): trades, fills, partial exits, stop changes, capital ledger.

P&L is always derived from recorded fills (manual entry of actual broker fills).
The original plan/thesis on a Trade is immutable (enforced at the ORM level).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload

from tradingos.db.models import CapitalFlow, Fill, StopChange, Trade, TradePlan, utcnow
from tradingos.db.session import session_scope
from tradingos.risk.engine import OpenPositionRisk
from tradingos.settings import TradingSettings

SETUPS = ["Breakout", "Pullback", "Momentum", "Earnings/catalyst", "Other"]
MISTAKE_TAGS = ["Chased entry", "No written plan", "Oversized", "Moved stop wider", "Exited early (fear)",
                "Held through earnings unplanned", "Ignored market regime", "FOMO / impulse", "Revenge trade",
                "Didn't take planned profit", "Late exit past stop"]


@dataclass
class TradeMetrics:
    bought: float
    sold: float
    open_qty: float
    avg_entry: float
    avg_exit: float | None
    fees: float
    realized_gross: float
    realized_net: float
    initial_risk_usd: float
    r_multiple: float | None
    holding_days: int | None
    first_entry: datetime | None
    last_exit: datetime | None


def compute_metrics(trade: Trade, as_of: datetime | None = None) -> TradeMetrics:
    buys = [f for f in trade.fills if f.side == "BUY"]
    sells = [f for f in trade.fills if f.side == "SELL"]
    bought = sum(f.qty for f in buys)
    sold = sum(f.qty for f in sells)
    avg_entry = sum(f.qty * f.price for f in buys) / bought if bought else 0.0
    avg_exit = sum(f.qty * f.price for f in sells) / sold if sold else None
    buy_fees = sum(f.commission + f.fx_cost + f.other_costs for f in buys)
    sell_fees = sum(f.commission + f.fx_cost + f.other_costs for f in sells)
    realized_gross = sum((f.price - avg_entry) * f.qty for f in sells)
    alloc_buy_fees = buy_fees * (sold / bought) if bought else 0.0
    realized_net = realized_gross - sell_fees - alloc_buy_fees
    first_entry = min((f.filled_at for f in buys), default=None)
    # initial risk uses the actual first entry price vs the ORIGINAL stop, on total bought qty
    entry_px = buys[0].price if buys else trade.planned_entry
    initial_risk = max(0.0, (entry_px - trade.initial_stop) * bought)
    last_exit = max((f.filled_at for f in sells), default=None)
    open_qty = round(bought - sold, 6)
    closed = open_qty <= 1e-9 and bought > 0
    r_mult = realized_net / initial_risk if (closed and initial_risk > 0) else None
    end = last_exit if closed else (as_of or utcnow())
    hold = (end.date() - first_entry.date()).days if first_entry and end else None
    return TradeMetrics(bought, sold, open_qty, avg_entry, avg_exit, buy_fees + sell_fees, realized_gross,
                        realized_net, initial_risk, r_mult, hold, first_entry, last_exit)


def _validate_fill(qty: float, price: float, fees: tuple[float, ...]) -> None:
    if qty <= 0:
        raise ValueError("Quantity must be positive.")
    if price <= 0:
        raise ValueError("Price must be positive.")
    if any(f < 0 for f in fees):
        raise ValueError("Fees cannot be negative.")


def open_trade(*, ticker: str, setup: str, entry_thesis: str, planned_entry: float, initial_stop: float,
               target1: float | None, target2: float | None, fill_price: float, qty: float,
               filled_at: datetime, commission: float = 0.0, fx_cost: float = 0.0, other_costs: float = 0.0,
               sector: str = "", plan_id: int | None = None, cfg: TradingSettings, equity: float,
               engine: Engine | None = None) -> int:
    ticker = ticker.strip().upper()
    if not ticker or not ticker.replace("-", "").replace(".", "").isalnum():
        raise ValueError("Invalid ticker.")
    if not entry_thesis.strip():
        raise ValueError("An entry thesis is required — write down why before you trade.")
    if initial_stop >= fill_price:
        raise ValueError("Initial stop must be below the entry fill (long-only).")
    _validate_fill(qty, fill_price, (commission, fx_cost, other_costs))
    with session_scope(engine) as s:
        t = Trade(ticker=ticker, sector=sector, setup=setup, plan_id=plan_id, entry_thesis=entry_thesis.strip(),
                  planned_entry=planned_entry, initial_stop=initial_stop, initial_target=target1,
                  initial_target2=target2, planned_risk_pct=cfg.risk_per_trade_pct, equity_at_entry=equity,
                  current_stop=initial_stop, status="OPEN")
        t.fills.append(Fill(side="BUY", filled_at=filled_at, qty=qty, price=fill_price, commission=commission,
                            fx_cost=fx_cost, other_costs=other_costs, note="Initial entry"))
        s.add(t)
        if plan_id:
            plan = s.get(TradePlan, plan_id)
            if plan:
                plan.status = "EXECUTED"
        s.flush()
        return t.id


def _load(s: Session, trade_id: int) -> Trade:
    t = s.get(Trade, trade_id)
    if t is None:
        raise ValueError(f"Trade {trade_id} not found.")
    return t


def record_exit(trade_id: int, *, qty: float, price: float, filled_at: datetime, commission: float = 0.0,
                fx_cost: float = 0.0, other_costs: float = 0.0, note: str = "", exit_reason: str = "",
                engine: Engine | None = None) -> dict:
    """Partial or full exit. Closes the trade when the open quantity reaches zero."""
    _validate_fill(qty, price, (commission, fx_cost, other_costs))
    with session_scope(engine) as s:
        t = _load(s, trade_id)
        if t.status != "OPEN":
            raise ValueError("Trade is already closed.")
        m = compute_metrics(t)
        if qty > m.open_qty + 1e-9:
            raise ValueError(f"Cannot sell {qty}; only {m.open_qty} open.")
        if m.first_entry and filled_at < m.first_entry:
            raise ValueError("Exit cannot be dated before the entry.")
        t.fills.append(Fill(side="SELL", filled_at=filled_at, qty=qty, price=price, commission=commission,
                            fx_cost=fx_cost, other_costs=other_costs, note=note))
        s.flush()
        m = compute_metrics(t)
        if m.open_qty <= 1e-9:
            t.status = "CLOSED"
            t.closed_at = filled_at
        if exit_reason:
            t.exit_reason = (t.exit_reason + "\n" if t.exit_reason else "") + \
                f"[{filled_at:%Y-%m-%d}] {qty:g} @ {price:.2f}: {exit_reason}"
        return {"status": t.status, "open_qty": m.open_qty, "realized_net": round(m.realized_net, 2)}


def change_stop(trade_id: int, new_stop: float, reason: str, engine: Engine | None = None) -> dict:
    if new_stop <= 0:
        raise ValueError("Stop must be positive.")
    with session_scope(engine) as s:
        t = _load(s, trade_id)
        if t.status != "OPEN":
            raise ValueError("Cannot change the stop on a closed trade.")
        old = t.current_stop
        if abs(new_stop - old) < 1e-9:
            raise ValueError("Stop is unchanged.")
        widened = new_stop < old
        s.add(StopChange(trade_id=t.id, old_stop=old, new_stop=new_stop,
                         reason=(("[WIDENED — risk increased] " if widened else "") + reason).strip()))
        t.current_stop = new_stop
        return {"old": old, "new": new_stop, "widened": widened}


def update_reflection(trade_id: int, *, lessons: str | None = None, chart_ref: str | None = None,
                      mistake_tags: list[str] | None = None, engine: Engine | None = None) -> None:
    """Only post-trade reflection fields are editable. The thesis is not."""
    with session_scope(engine) as s:
        t = _load(s, trade_id)
        if lessons is not None:
            t.lessons = lessons
        if chart_ref is not None:
            t.chart_ref = chart_ref
        if mistake_tags is not None:
            t.mistake_tags = ",".join(mistake_tags)


def load_trades(status: str | None = None, engine: Engine | None = None) -> list[Trade]:
    with session_scope(engine) as s:
        q = select(Trade).options(selectinload(Trade.fills), selectinload(Trade.stop_changes))
        if status:
            q = q.where(Trade.status == status)
        return list(s.scalars(q.order_by(Trade.created_at)).all())


def trades_dataframe(status: str | None = None, engine: Engine | None = None) -> pd.DataFrame:
    rows = []
    for t in load_trades(status, engine):
        m = compute_metrics(t)
        rows.append({
            "id": t.id, "ticker": t.ticker, "sector": t.sector, "setup": t.setup, "status": t.status,
            "entry_date": m.first_entry, "exit_date": m.last_exit if t.status == "CLOSED" else None,
            "planned_entry": t.planned_entry, "avg_entry": round(m.avg_entry, 4), "qty": m.bought,
            "open_qty": m.open_qty, "initial_stop": t.initial_stop, "current_stop": t.current_stop,
            "target": t.initial_target, "target2": t.initial_target2, "avg_exit": m.avg_exit,
            "fees_total": round(m.fees, 4),
            "fx_costs": round(sum(f.fx_cost for f in t.fills), 4),
            "realized_net": round(m.realized_net, 2), "initial_risk_usd": round(m.initial_risk_usd, 2),
            "r_multiple": None if m.r_multiple is None else round(m.r_multiple, 2),
            "holding_days": m.holding_days, "planned_risk_pct": t.planned_risk_pct,
            "equity_at_entry": t.equity_at_entry, "entry_thesis": t.entry_thesis, "exit_reason": t.exit_reason,
            "lessons": t.lessons, "chart_ref": t.chart_ref, "mistake_tags": t.mistake_tags,
            "stop_changes": len(t.stop_changes),
            "stop_widened": any(sc.new_stop < sc.old_stop for sc in t.stop_changes),
        })
    return pd.DataFrame(rows)


def fills_dataframe(engine: Engine | None = None) -> pd.DataFrame:
    with session_scope(engine) as s:
        rows = s.execute(select(Fill, Trade.ticker).join(Trade)).all()
        return pd.DataFrame([{"trade_id": f.trade_id, "ticker": tk, "side": f.side, "filled_at": f.filled_at,
                              "qty": f.qty, "price": f.price, "commission": f.commission, "fx_cost": f.fx_cost,
                              "other_costs": f.other_costs, "note": f.note} for f, tk in rows])


# ----------------------------------------------------------------- capital ledger
def add_capital_flow(kind: str, amount_usd: float, flow_date: date, inr_amount: float | None = None,
                     fx_rate: float | None = None, fx_cost_usd: float = 0.0, notes: str = "",
                     engine: Engine | None = None) -> None:
    if kind not in ("DEPOSIT", "WITHDRAWAL"):
        raise ValueError("kind must be DEPOSIT or WITHDRAWAL")
    if amount_usd <= 0 or fx_cost_usd < 0:
        raise ValueError("Amount must be positive; FX cost non-negative.")
    with session_scope(engine) as s:
        s.add(CapitalFlow(flow_date=flow_date, kind=kind, amount_usd=amount_usd, inr_amount=inr_amount,
                          fx_rate=fx_rate, fx_cost_usd=fx_cost_usd, notes=notes))


def capital_flows_dataframe(engine: Engine | None = None) -> pd.DataFrame:
    with session_scope(engine) as s:
        rows = s.scalars(select(CapitalFlow).order_by(CapitalFlow.flow_date)).all()
        return pd.DataFrame([{"date": r.flow_date, "kind": r.kind, "amount_usd": r.amount_usd,
                              "inr_amount": r.inr_amount, "fx_rate": r.fx_rate, "fx_cost_usd": r.fx_cost_usd,
                              "notes": r.notes} for r in rows])


def account_state(cfg: TradingSettings, prices: dict[str, float] | None = None,
                  engine: Engine | None = None) -> dict:
    """Trading-account equity. Long-term investments are NEVER included (separate database)."""
    flows = capital_flows_dataframe(engine)
    dep = flows.loc[flows["kind"] == "DEPOSIT", "amount_usd"].sum() if len(flows) else 0.0
    wd = flows.loc[flows["kind"] == "WITHDRAWAL", "amount_usd"].sum() if len(flows) else 0.0
    fxc = flows["fx_cost_usd"].sum() if len(flows) else 0.0
    contributed = cfg.starting_capital_usd + dep - wd
    realized = 0.0
    open_cost = 0.0
    unrealized = 0.0
    unpriced = []
    positions: list[OpenPositionRisk] = []
    for t in load_trades(engine=engine):
        m = compute_metrics(t)
        realized += m.realized_net
        if t.status == "OPEN" and m.open_qty > 0:
            buy_fees = sum(f.commission + f.fx_cost + f.other_costs for f in t.fills if f.side == "BUY")
            remaining_fee = buy_fees * (m.open_qty / m.bought) if m.bought else 0
            open_cost += m.avg_entry * m.open_qty + remaining_fee
            positions.append(OpenPositionRisk(t.ticker, m.open_qty, m.avg_entry, t.current_stop, t.sector))
            px = (prices or {}).get(t.ticker)
            if px:
                unrealized += (px - m.avg_entry) * m.open_qty - remaining_fee
            else:
                unpriced.append(t.ticker)
    # cash = contributed − transfer FX costs + realized P&L − (open shares at cost + their unallocated entry fees)
    cash = contributed - fxc + realized - open_cost
    equity_book = cash + open_cost                       # open positions valued at cost
    equity_mark = cash + open_cost + unrealized if not unpriced else None  # = cash + Σ open_qty × price
    return {"starting_capital": cfg.starting_capital_usd, "deposits": dep, "withdrawals": wd,
            "fx_costs_on_transfers": fxc, "net_contributed": contributed, "realized_pnl": round(realized, 2),
            "open_cost_basis": round(open_cost, 2), "cash": round(cash, 2),
            "equity_at_cost": round(equity_book, 2),
            "unrealized_pnl": round(unrealized, 2) if not unpriced else None,
            "equity_marked": round(equity_mark, 2) if equity_mark is not None else None,
            "unpriced_positions": unpriced, "open_positions": positions,
            "open_risk": round(sum(p.risk for p in positions), 2)}


def sizing_equity(state: dict) -> float:
    """Equity used for risk sizing: marked-to-market if all positions priced, else at cost."""
    return state["equity_marked"] if state.get("equity_marked") is not None else state["equity_at_cost"]
