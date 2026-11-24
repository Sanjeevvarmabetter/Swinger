from datetime import date, datetime, timedelta, timezone

import numpy as np

from tradingos.data.base import NY, Freshness, classify_bar_freshness, is_trading_day, nyse_holidays
from tradingos.data.news import (classify_category, classify_info_type, classify_sentiment, dedupe_key, query_news,
                                 refresh_news)
from tests.conftest import make_ohlcv


def test_nyse_holidays_2026():
    h = nyse_holidays(2026)
    assert date(2026, 11, 26) in h      # Thanksgiving
    assert date(2026, 4, 3) in h        # Good Friday
    assert date(2026, 7, 3) in h        # Independence Day observed (Jul 4 is Saturday)
    assert date(2026, 6, 19) in h       # Juneteenth
    assert not is_trading_day(date(2026, 11, 28))  # Saturday


def test_freshness_classification():
    after_close = datetime(2026, 11, 24, 17, 0, tzinfo=NY)  # Tuesday after close
    assert classify_bar_freshness(date(2026, 11, 24), after_close) == Freshness.CURRENT
    assert classify_bar_freshness(date(2026, 11, 23), after_close) == Freshness.STALE
    assert classify_bar_freshness(date(2026, 11, 10), after_close) == Freshness.VERY_STALE
    during = datetime(2026, 11, 24, 11, 0, tzinfo=NY)
    assert classify_bar_freshness(date(2026, 11, 24), during) == Freshness.INTRADAY_DELAYED
    assert classify_bar_freshness(date(2026, 11, 23), during) == Freshness.CURRENT
    # Friday after Thanksgiving morning: last completed session is Wednesday
    assert classify_bar_freshness(date(2026, 11, 25), datetime(2026, 11, 27, 8, 0, tzinfo=NY)) == Freshness.CURRENT
    assert classify_bar_freshness(None) == Freshness.MISSING


def test_news_classification():
    assert classify_category("US imposes new chip export controls on China") == "geopolitics"
    assert classify_category("Fed holds interest rates steady as inflation cools") == "macro"
    assert classify_sentiment("Stock surges after earnings beat") == "positive"
    assert classify_sentiment("Shares plunge on guidance cut") == "negative"
    assert classify_info_type("Apple reportedly in talks to buy startup", False).startswith("Speculation")
    assert classify_info_type("FOMC statement", True).startswith("Confirmed")
    assert dedupe_key("Nvidia beats estimates!") == dedupe_key("nvidia beats  estimates")


def test_refresh_news_dedupes_and_drops_stale(monkeypatch):
    from tradingos.data import news
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    items = [
        {"headline": "Fed cuts rates", "summary": "", "source": "Fed", "url": "u1", "published_at": now},
        {"headline": "FED CUTS RATES", "summary": "", "source": "CNBC", "url": "u2", "published_at": now},
        {"headline": "Old story", "summary": "", "source": "CNBC", "url": "u3", "published_at": now - timedelta(days=30)},
        {"headline": "Undated", "summary": "", "source": "CNBC", "url": "u4", "published_at": None},
    ]
    monkeypatch.setattr(news, "load_feed_config", lambda: [{"name": "x", "url": "x"}])
    monkeypatch.setattr(news, "fetch_rss", lambda feed: [news.enrich(dict(i)) for i in items])
    st = refresh_news([], max_age_days=7)
    assert st["stored"] == 1 and st["duplicates"] == 1 and st["stale"] == 2
    st2 = refresh_news([], max_age_days=7)
    assert st2["stored"] == 0
    assert len(query_news(days=7)) == 1


def test_feed_failure_is_reported_not_raised(monkeypatch):
    from tradingos.data import news
    monkeypatch.setattr(news, "load_feed_config", lambda: [{"name": "Broken", "url": "x"}])
    def boom(feed):
        raise ConnectionError("down")
    monkeypatch.setattr(news, "fetch_rss", boom)
    st = refresh_news([], 7)
    assert st["stored"] == 0 and "Broken" in st["errors"][0]


def test_stock_context_missing_price(fake_provider):
    from tradingos import services
    from tradingos.settings import AppSettings
    fake_provider({})
    ctx = services.stock_context("ZZZZ", AppSettings(), with_fundamentals=False)
    assert "error" in ctx


def test_stock_context_has_snapshot_and_no_trade_fields(fake_provider, uptrend):
    from tradingos import services
    from tradingos.settings import AppSettings
    fake_provider({"SPY": uptrend, "TEST": uptrend})
    ctx = services.stock_context("TEST", AppSettings(), with_fundamentals=False)
    assert "error" not in ctx and ctx["daily"]["close"] > 0
    assert not hasattr(services, "build_trade_plan")


def test_batch_as_of_flags_lagging_tickers():
    from tradingos.data.providers import _lagging, _last_bar_date
    a = make_ohlcv(np.full(40, 10.0))
    b = a.iloc[:-3]
    frames = {"A": a, "B": a, "C": b}
    as_of = _last_bar_date(frames)
    assert as_of == a.index[-1].date()
    assert _lagging(frames, as_of) == [f"C (last bar {b.index[-1].date()})"]
