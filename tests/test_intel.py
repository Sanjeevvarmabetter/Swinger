"""Tests for the global intelligence layer (offline — network is blocked where relevant)."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv

IST = ZoneInfo("Asia/Kolkata")


def utc(y, m, d, hh, mm, tz):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


# ----------------------------------------------------------------------------- freshness
def test_india_holiday_flagged_not_hidden():
    from tradingos.data.base import Freshness
    from tradingos.intel.freshness import bar_freshness
    # Tue 24 Nov 2026 20:00 IST, last NSE bar Mon 23 Nov (24th was an NSE holiday)
    f, note = bar_freshness(date(2026, 11, 23), "IN", utc(2026, 11, 24, 20, 0, "Asia/Kolkata"))
    assert f == Freshness.STALE and "holiday" in note


def test_india_intraday_and_weekend():
    from tradingos.data.base import Freshness
    from tradingos.intel.freshness import bar_freshness
    f, _ = bar_freshness(date(2026, 11, 25), "IN", utc(2026, 11, 25, 11, 0, "Asia/Kolkata"))
    assert f == Freshness.INTRADAY_DELAYED
    f, _ = bar_freshness(date(2026, 11, 27), "IN", utc(2026, 11, 29, 9, 0, "Asia/Kolkata"))  # Sunday, Friday bar
    assert f == Freshness.CURRENT
    f, _ = bar_freshness(date(2026, 11, 18), "IN", utc(2026, 11, 25, 18, 0, "Asia/Kolkata"))
    assert f == Freshness.VERY_STALE


def test_missing_bar():
    from tradingos.data.base import Freshness
    from tradingos.intel.freshness import bar_freshness
    assert bar_freshness(None, "JP")[0] == Freshness.MISSING


# ----------------------------------------------------------------------------- schedule
def test_us_premarket_tracks_dst():
    from tradingos.intel.briefing import EDITIONS, scheduled_at
    ed = EDITIONS["us_premarket"]
    assert scheduled_at(ed, date(2026, 12, 1)).astimezone(IST).strftime("%H:%M") == "18:00"   # EST
    assert scheduled_at(ed, date(2026, 7, 1)).astimezone(IST).strftime("%H:%M") == "17:00"    # EDT


def test_due_editions_grace_and_dedupe():
    from tradingos.intel import briefing as br
    from tradingos.db.models import Briefing
    from tradingos.db.session import session_scope
    now = utc(2026, 11, 25, 7, 20, "Asia/Kolkata")          # Wed 07:20 IST
    assert "global_morning" in br.due_editions(now)
    assert "india_open" not in br.due_editions(now)
    with session_scope() as s:
        s.add(Briefing(edition="global_morning", edition_date=date(2026, 11, 25), deterministic_md="x"))
    assert "global_morning" not in br.due_editions(now)
    assert br.due_editions(utc(2026, 11, 25, 12, 0, "Asia/Kolkata")) == []                  # past both grace windows


def test_weekly_and_monthly_days():
    from tradingos.intel.briefing import EDITIONS, runs_on
    assert runs_on(EDITIONS["weekly_review"], date(2026, 11, 28))       # Saturday
    assert not runs_on(EDITIONS["weekly_review"], date(2026, 11, 27))
    assert runs_on(EDITIONS["monthly_review"], date(2026, 12, 1))
    assert not runs_on(EDITIONS["monthly_review"], date(2026, 12, 2))


# ----------------------------------------------------------------------------- news
def test_keyword_word_boundaries():
    from tradingos.data.news import classify_category, classify_sentiment, kw_hit
    assert not kw_hit("AI boom looms over Warsh's Fed", "war")
    assert kw_hit("Trade war escalates", "war")
    assert not kw_hit("Bank shares climb", "ban")
    assert kw_hit("Semiconductors rally", "semiconductor")
    assert classify_category("AI boom looms over Warsh's Fed as inflation worries grow") == "macro"
    assert classify_sentiment("Bank of America shares climb") != "negative"


def test_region_classification():
    from tradingos.data.news import classify_region
    assert classify_region("Wall Street soars as Nasdaq jumps", hint="India") == "US"
    assert classify_region("Sensex ends higher", hint="India") == "India"
    assert classify_region("RBI announces auction of government securities", hint="India", official=True) == "India"
    assert classify_region("Something happened somewhere") == "Global"


def _news(rows):
    return pd.DataFrame([{"published_utc": pd.Timestamp("2026-11-24 10:00") - pd.Timedelta(minutes=i),
                          "summary": "", "url": f"https://x/{i}", "tickers": "", "impact": "", "region": "US",
                          "category": "markets", "info_type": "Reported (news media)", "sector": "",
                          "sentiment": "neutral", **r} for i, r in enumerate(rows)])


def test_clustering_and_corroboration():
    from tradingos.intel.news_rank import rank_news
    df = _news([
        {"headline": "Nvidia shares soar 31% as Jensen Huang's return sparks Wall Street rally", "source": "A"},
        {"headline": "Tech stocks see monster rally after Jensen Huang returns as Nvidia CEO", "source": "B"},
        {"headline": "Wall Street soars on Huang's return to Nvidia, Treasury yields rise", "source": "C"},
        {"headline": "Brazil coffee harvest forecast trimmed", "source": "D"},
    ])
    r = rank_news(df, now=datetime(2026, 11, 24, 12))
    assert len(r) == 2
    top = r.iloc[0]
    assert top["n_sources"] == 3 and "Nvidia" in top["headline"]
    assert top["score"] > r.iloc[1]["score"]


def test_routine_official_notice_downranked():
    from tradingos.intel.news_rank import rank_news
    df = _news([
        {"headline": "RBI to conduct Overnight Variable Rate Repo (VRR) auction", "source": "RBI",
         "info_type": "Confirmed (official source)", "category": "macro", "region": "India"},
        {"headline": "Federal Reserve holds rates steady, signals cuts in 2027", "source": "Fed",
         "info_type": "Confirmed (official source)", "category": "macro"},
    ])
    r = rank_news(df, now=datetime(2026, 11, 24, 12)).set_index("source")
    assert r.loc["Fed", "score"] > r.loc["RBI", "score"]
    assert r.loc["Fed", "tier"] == "MUST KNOW"


def test_rank_empty():
    from tradingos.intel.news_rank import rank_news
    assert rank_news(pd.DataFrame()).empty


# ----------------------------------------------------------------------------- gold & risk
def test_inr_conversion():
    from tradingos.intel.gold import inr_per_10g
    assert inr_per_10g(3110.34768, 100) == 100000.0
    assert inr_per_10g(None, 90) is None


def test_attribution_reading():
    from tradingos.intel.gold import attribution_reading
    drivers = [{"Driver": "US dollar (DXY)", "Conventional effect on gold": "supportive"},
               {"Driver": "10Y real yield (TIPS)", "Conventional effect on gold": "negative"}]
    txt = attribution_reading(4.0, drivers)
    assert "up 4.0%" in txt and "US dollar" in txt and "other way" in txt
    assert "unavailable" in attribution_reading(None, drivers)


def test_positioning_summary():
    from tradingos.intel.gold import positioning_summary
    d = pd.DataFrame({"date": pd.date_range("2025-01-07", periods=10, freq="7D").date,
                      "mm_net": list(range(10, 110, 10)), "mm_net_pct_oi": [5.0] * 10})
    s = positioning_summary(d)
    assert s["mm_net"] == 100 and s["weekly_change"] == 10 and s["percentile_in_window"] == 100
    assert "Crowded" in s["reading"]


def _snap(values: dict) -> pd.DataFrame:
    rows = []
    for sym, v in values.items():
        rows.append({"Symbol": sym, "Name": sym, "Last": v.get("Last", 1.0), "1W %": v.get("1W %"),
                     "1M %": v.get("1M %"), "Above 200DMA": v.get("Above 200DMA")})
    return pd.DataFrame(rows)


def test_risk_appetite_rules():
    from tradingos.intel.markets import risk_appetite
    off = _snap({"^VIX": {"Last": 32}, "^GSPC": {"1M %": 0.0, "Above 200DMA": False}, "HYG": {"1M %": -3},
                 "LQD": {"1M %": 0}, "HG=F": {"1M %": -6}, "GC=F": {"1M %": 2}})
    r = risk_appetite(off, hy_spread=5.6)
    assert r["label"] == "Risk-off" and r["risk_off"] >= 4
    assert risk_appetite(pd.DataFrame(columns=["Symbol", "Last"]))["label"].startswith("Unknown")


# ----------------------------------------------------------------------------- migration
def test_add_missing_columns(tmp_path):
    import sqlite3
    from tradingos.db.models import TradingBase
    from tradingos.db.session import add_missing_columns, make_engine
    p = tmp_path / "old.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE news_items (id INTEGER PRIMARY KEY, dedupe_key VARCHAR(64), headline TEXT)")
    eng = make_engine(p)
    added = add_missing_columns(eng, TradingBase)
    assert "news_items.region" in added
    assert add_missing_columns(eng, TradingBase) == []          # idempotent


# ----------------------------------------------------------------------------- end-to-end offline
@pytest.fixture
def offline(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("network disabled in tests")
    monkeypatch.setattr(requests, "get", boom)


def test_payload_and_markdown_with_partial_data(fake_provider, offline):
    """Only a few instruments return data and every HTTP source fails: the briefing must still build,
    show missing data explicitly and invent nothing."""
    from tradingos.intel import briefing as br
    rng = np.random.default_rng(1)
    frames = {s: make_ohlcv(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), start="2025-09-01")
              for s in ["^GSPC", "^NDX", "GC=F", "^VIX", "SI=F"]}
    fake_provider(frames)
    p = br.build_payload("global_morning", now=datetime(2026, 11, 24, 2, 0, tzinfo=timezone.utc))
    assert p["markets"]["us_indices"] and p["gold"]["gold"]["Last"] > 0
    assert "^NSEI" in p["data_quality"]["missing_symbols"]
    assert any("FRED" in e or "network" in e or "CFTC" in e for e in p["data_quality"]["errors"]) or p["gold"]["errors"]
    assert p["news_ranked"] == [] and p["upcoming_earnings_watchlist"] == []
    md = br.deterministic_markdown(p)
    assert "Global Morning Briefing" in md and "Missing:" in md and "Nothing in this tier" in md
    assert "Nifty 50 | —" in md or "Nifty 50" in md


def test_generate_without_ai_archives(fake_provider, offline):
    from tradingos.intel import briefing as br
    fake_provider({"^GSPC": make_ohlcv(np.linspace(100, 120, 300))})
    b = br.generate("india_open", use_ai=True, refresh=False)
    assert b.id and b.deterministic_md and b.ai_md == "" and "not configured" in b.ai_error
    assert br.latest("india_open").id == b.id
