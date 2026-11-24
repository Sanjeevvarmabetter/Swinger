"""SQLAlchemy models.

Two separate declarative bases → two separate SQLite files:
  * TradingBase  → trading.db   (swing-trading capital, journal, plans, research)
  * LongTermBase → longterm.db  (long-term investments; monitoring only)
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.orm.attributes import get_history


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TradingBase(DeclarativeBase):
    pass


class LongTermBase(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- trading.db
class Setting(TradingBase):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CapitalFlow(TradingBase):
    """Deposits/withdrawals of ACTIVE TRADING capital only (USD)."""
    __tablename__ = "capital_flows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))  # DEPOSIT | WITHDRAWAL
    amount_usd: Mapped[float] = mapped_column(Float)  # always positive
    inr_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WatchlistItem(TradingBase):
    __tablename__ = "watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(256), default="")
    alert_above: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_below: Mapped[float | None] = mapped_column(Float, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TradePlan(TradingBase):
    __tablename__ = "trade_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ticker: Mapped[str] = mapped_column(String(16))
    setup: Mapped[str] = mapped_column(String(32))
    thesis: Mapped[str] = mapped_column(Text, default="")
    entry_trigger: Mapped[str] = mapped_column(Text, default="")
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target1: Mapped[float | None] = mapped_column(Float, nullable=True)
    target2: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares: Mapped[float] = mapped_column(Float, default=0)
    risk_usd: Mapped[float] = mapped_column(Float, default=0)
    reward_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_period: Mapped[str] = mapped_column(String(64), default="2-4 weeks")
    catalyst: Mapped[str] = mapped_column(Text, default="")
    risks: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str] = mapped_column(String(32))
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    data_as_of: Mapped[str] = mapped_column(String(64), default="")
    ai_review: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE | EXECUTED | CANCELLED


class Trade(TradingBase):
    """A swing trade. Original-plan fields are IMMUTABLE after creation (see listener below)."""
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16))
    sector: Mapped[str] = mapped_column(String(64), default="")
    setup: Mapped[str] = mapped_column(String(32))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id"), nullable=True)
    # ---- immutable original plan ----
    entry_thesis: Mapped[str] = mapped_column(Text)
    planned_entry: Mapped[float] = mapped_column(Float)
    initial_stop: Mapped[float] = mapped_column(Float)
    initial_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_target2: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_risk_pct: Mapped[float] = mapped_column(Float)  # risk % configured when opened
    equity_at_entry: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # ---- mutable lifecycle ----
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | CLOSED
    current_stop: Mapped[float] = mapped_column(Float)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_reason: Mapped[str] = mapped_column(Text, default="")
    lessons: Mapped[str] = mapped_column(Text, default="")
    chart_ref: Mapped[str] = mapped_column(Text, default="")
    mistake_tags: Mapped[str] = mapped_column(String(256), default="")

    fills: Mapped[list["Fill"]] = relationship(back_populates="trade", cascade="all, delete-orphan",
                                               order_by="Fill.filled_at")
    stop_changes: Mapped[list["StopChange"]] = relationship(back_populates="trade", cascade="all, delete-orphan",
                                                            order_by="StopChange.changed_at")


IMMUTABLE_TRADE_FIELDS = ("entry_thesis", "planned_entry", "initial_stop", "initial_target",
                          "initial_target2", "planned_risk_pct", "equity_at_entry", "ticker", "setup")


class ImmutableFieldError(Exception):
    pass


@event.listens_for(Session, "before_flush")
def _protect_original_thesis(session, flush_context, instances):  # noqa: ARG001
    for obj in session.dirty:
        if isinstance(obj, Trade):
            for f in IMMUTABLE_TRADE_FIELDS:
                hist = get_history(obj, f)
                if hist.deleted and hist.added and hist.deleted[0] != hist.added[0]:
                    raise ImmutableFieldError(
                        f"Trade.{f} is part of the original plan and cannot be modified. "
                        "Record a note, stop change or lesson instead.")


class Fill(TradingBase):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"))
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    filled_at: Mapped[datetime] = mapped_column(DateTime)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    fx_cost: Mapped[float] = mapped_column(Float, default=0.0)
    other_costs: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    trade: Mapped[Trade] = relationship(back_populates="fills")


class StopChange(TradingBase):
    __tablename__ = "stop_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    old_stop: Mapped[float] = mapped_column(Float)
    new_stop: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    trade: Mapped[Trade] = relationship(back_populates="stop_changes")


class NewsItem(TradingBase):
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("dedupe_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    tickers: Mapped[str] = mapped_column(String(256), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    sector: Mapped[str] = mapped_column(String(64), default="")
    sentiment: Mapped[str] = mapped_column(String(16), default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    info_type: Mapped[str] = mapped_column(String(32), default="")  # confirmed | interpretation | speculation
    region: Mapped[str] = mapped_column(String(16), default="")  # US | India | Global | Europe | Asia (feed/keyword)


class AIReport(TradingBase):
    __tablename__ = "ai_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(48))
    subject: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    input_json: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")


class EconEvent(TradingBase):
    __tablename__ = "econ_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(32), default="macro")
    importance: Mapped[str] = mapped_column(String(8), default="medium")
    source_url: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    country: Mapped[str] = mapped_column(String(32), default="")
    event_time: Mapped[str] = mapped_column(String(32), default="")   # free text local time, e.g. "10:00 IST"


class Briefing(TradingBase):
    """Archived intelligence briefing (deterministic facts + optional Gemini edition)."""
    __tablename__ = "briefings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition: Mapped[str] = mapped_column(String(48))          # key from tradingos.intel.briefing.EDITIONS
    edition_date: Mapped[date] = mapped_column(Date)           # IST calendar date the edition belongs to
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deterministic_md: Mapped[str] = mapped_column(Text, default="")
    ai_md: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    ai_error: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="")


class ScanRun(TradingBase):
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    data_as_of: Mapped[str] = mapped_column(String(64), default="")
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    results_json: Mapped[str] = mapped_column(Text, default="[]")


class Alert(TradingBase):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ticker: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- longterm.db
class LongTermHolding(LongTermBase):
    __tablename__ = "lt_holdings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(32))  # US ETF | US Stock | Indian MF | Indian Stock | Gold | Other
    symbol: Mapped[str] = mapped_column(String(64))  # yfinance symbol, mfapi scheme code, or label
    name: Mapped[str] = mapped_column(String(128), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    price_source: Mapped[str] = mapped_column(String(16), default="yfinance")  # yfinance | mfapi | manual
    manual_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_price_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
