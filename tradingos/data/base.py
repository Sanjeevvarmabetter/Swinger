"""Provider-agnostic result wrapper + data-freshness logic.

Every provider returns a DataResult so the UI can always show: source, retrieval time,
market-data timestamp, freshness and missing-data status. Nothing is presented as
real-time unless it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Generic, TypeVar
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
T = TypeVar("T")


class Freshness(str, Enum):
    INTRADAY_DELAYED = "Intraday (delayed — not real-time)"
    CURRENT = "Current (latest completed session)"
    STALE = "Stale"
    VERY_STALE = "Very stale"
    MISSING = "Missing"
    STATIC = "Periodic release"  # macro series published monthly/quarterly


@dataclass
class DataResult(Generic[T]):
    data: T | None
    source: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    as_of: datetime | date | None = None          # market-data timestamp (last bar / publication)
    freshness: Freshness = Freshness.MISSING
    missing: list[str] = field(default_factory=list)
    error: str | None = None
    notes: str = ""

    @property
    def ok(self) -> bool:
        return self.data is not None and self.error is None

    def meta(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "retrieved_at_utc": self.retrieved_at.strftime("%Y-%m-%d %H:%M UTC"),
            "data_as_of": str(self.as_of) if self.as_of else None,
            "freshness": self.freshness.value,
            "missing": self.missing,
            "error": self.error,
        }


# ----------------------------------------------------------------- NYSE trading calendar
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:  # Anonymous Gregorian algorithm
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> set[date]:
    """Full-day NYSE holidays (standard rules; special closures are not modelled)."""
    hol = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),            # MLK Day
        _nth_weekday(year, 2, 0, 3),            # Presidents Day
        _easter(year) - timedelta(days=2),      # Good Friday
        _last_weekday(year, 5, 0),              # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),            # Labor Day
        _nth_weekday(year, 11, 3, 4),           # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        hol.add(_observed(date(year, 6, 19)))   # Juneteenth
    # New Year's falling on Saturday is NOT observed on the prior Friday by NYSE
    if date(year, 1, 1).weekday() == 5:
        hol.discard(date(year - 1, 12, 31))
    return hol


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def trading_days_between(a: date, b: date) -> int:
    """Number of trading days strictly after a, up to and including b."""
    if b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


MARKET_OPEN, MARKET_CLOSE = time(9, 30), time(16, 0)


def market_status(now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    if not is_trading_day(now.date()):
        return "Closed (non-trading day)"
    if now.time() < MARKET_OPEN:
        return "Pre-market"
    if now.time() >= MARKET_CLOSE:
        return "After hours"
    return "Open"


def last_completed_session(now: datetime | None = None) -> date:
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    if is_trading_day(now.date()) and now.time() >= MARKET_CLOSE:
        return now.date()
    return previous_trading_day(now.date())


def classify_bar_freshness(last_bar: date | None, now: datetime | None = None) -> Freshness:
    if last_bar is None:
        return Freshness.MISSING
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    if last_bar == now.date() and market_status(now) == "Open":
        return Freshness.INTRADAY_DELAYED
    expected = last_completed_session(now)
    if last_bar >= expected:
        return Freshness.CURRENT
    lag = trading_days_between(last_bar, expected)
    return Freshness.STALE if lag <= 2 else Freshness.VERY_STALE
