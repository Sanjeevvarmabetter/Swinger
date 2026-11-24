"""Per-exchange freshness of daily bars.

The NYSE calendar (with holidays) is reused for US instruments. Other exchanges use a weekday calendar
with the local session close; exchange holidays are not modelled, so a one-session lag is reported as
"possible holiday or provider lag" rather than silently called current or stale.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from tradingos.data.base import Freshness, classify_bar_freshness
from tradingos.intel.instruments import MARKETS


def _prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def expected_last_bar(market_key: str, now: datetime | None = None) -> date:
    """Date of the most recent session that should be complete at `now`."""
    m = MARKETS[market_key]
    local = (now or datetime.now(timezone.utc)).astimezone(m.tz)
    if not m.weekdays_only:
        return local.date()
    d = local.date()
    if d.weekday() < 5 and local.time() >= m.close:
        return d
    return _prev_weekday(d)


def weekday_lag(last_bar: date, expected: date) -> int:
    n, d = 0, last_bar
    while d < expected:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def bar_freshness(last_bar: date | None, market_key: str, now: datetime | None = None) -> tuple[Freshness, str]:
    """Return (freshness, human note) for a daily bar dated `last_bar` on `market_key`."""
    if last_bar is None:
        return Freshness.MISSING, "No data returned."
    now = now or datetime.now(timezone.utc)
    m = MARKETS[market_key]
    if market_key == "US":
        f = classify_bar_freshness(last_bar, now)
        return f, m.calendar_note
    local = now.astimezone(m.tz)
    if not m.weekdays_only:
        if last_bar >= local.date():
            return Freshness.INTRADAY_DELAYED, "Current UTC day, still trading (24×7)."
        lag = (local.date() - last_bar).days
        return (Freshness.CURRENT, "Previous UTC day.") if lag <= 1 else (Freshness.STALE, f"{lag} days old.")
    if last_bar == local.date() and local.weekday() < 5 and local.time() < m.close:
        return Freshness.INTRADAY_DELAYED, f"{m.label} session in progress — delayed, not real-time."
    expected = expected_last_bar(market_key, now)
    if last_bar >= expected:
        return Freshness.CURRENT, m.calendar_note
    lag = weekday_lag(last_bar, expected)
    if lag == 1:
        return Freshness.STALE, f"1 session behind expected {expected:%d %b} — possible {m.label} holiday or provider lag."
    return Freshness.VERY_STALE, f"{lag} sessions behind expected {expected:%d %b}."
