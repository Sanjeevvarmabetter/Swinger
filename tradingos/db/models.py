"""SQLAlchemy models for the intelligence database (data/trading.db — filename kept for continuity).

Trading/portfolio tables (trades, fills, trade_plans, capital_flows, watchlist, scan_runs, alerts) were removed from
the code in the Nov-2026 cleanup. Existing tables in an old database file are left untouched (never dropped
automatically); see QA_REPORT.md for the optional manual clean-up command.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TradingBase(DeclarativeBase):
    pass


class Setting(TradingBase):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


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


class ChatMessage(TradingBase):
    """AI Research Chat history (persisted so a page refresh or restart does not lose the conversation)."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    role: Mapped[str] = mapped_column(String(16))            # user | assistant | error
    text: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")   # [{"title","source","url","published"}]
