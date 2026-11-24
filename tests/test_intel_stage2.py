"""Stage 2: geopolitics, trends radar, economic calendar, news intelligence (offline)."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv

NOW = datetime(2026, 11, 24, 12, 0)


def _news(rows, now=NOW):
    base = {"summary": "", "url": "https://x", "tickers": "", "impact": "", "region": "Global", "category": "geopolitics",
            "info_type": "Reported (news media)", "sector": "", "sentiment": "neutral"}
    out = []
    for i, r in enumerate(rows):
        d = {**base, "url": f"https://x/{i}", **r}
        d["published_utc"] = now - timedelta(hours=r.get("hours_ago", i))
        d.pop("hours_ago", None)
        out.append(d)
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- FOMC parser
FED_HTML = """
<h4>2026 FOMC Meetings</h4>
<div class="fomc-meeting__month col-xs-5"><strong>October</strong></div>
<div class="fomc-meeting__date col-xs-4">27-28</div>
<div class="fomc-meeting__month col-xs-5"><strong>December</strong></div>
<div class="fomc-meeting__date col-xs-4">8-9*</div>
<h4>2027 FOMC Meetings</h4>
<div class="fomc-meeting__month col-xs-5"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col-xs-4">30-1</div>
"""


def test_parse_fomc_html():
    from tradingos.intel.calendars import parse_fomc_html
    m = parse_fomc_html(FED_HTML)
    assert [x["decision_date"] for x in m] == [date(2026, 10, 28), date(2026, 12, 9), date(2027, 5, 1)]
    assert m[1]["sep"] and not m[0]["sep"]


def test_fomc_ist_conversion():
    from datetime import time
    from tradingos.intel.calendars import to_ist
    assert to_ist(date(2026, 12, 9), time(14, 0)) == "Thu 10 Dec 00:30 IST"     # EST
    assert to_ist(date(2026, 7, 29), time(14, 0)) == "Wed 29 Jul 23:30 IST"     # EDT


def test_superseded_release_never_claims_actual():
    from tradingos.intel.calendars import release_readings
    out = release_readings(10, date(2026, 10, 15), superseded=True)
    assert out and all("superseded" in r["status"] and "actual" not in r for r in out)


def test_relevance_mapping():
    from tradingos.intel.calendars import relevance_for
    assert "Fed" in relevance_for("US CPI (BLS)")
    assert relevance_for("Some unknown event") == ""


# ----------------------------------------------------------------------------- geopolitics
def test_theater_matching_word_boundaries():
    from tradingos.intel.geopolitics import match_theaters
    assert "iran" in match_theaters("Iran tanker traffic through Hormuz drops")
    assert "energy_shipping" in match_theaters("Iran tanker traffic through Hormuz drops")
    assert match_theaters("Fed's Warsh speaks about rates and the labour market") == []
    assert "russia_ukraine" in match_theaters("Ukrainians brace for winter strikes")
    assert match_theaters("Apple launches a new iPhone") == []


def test_attention_and_event_cards():
    from tradingos.intel import geopolitics as geo
    df = _news([
        {"headline": "Iran threatens to close Strait of Hormuz after strikes", "source": "A", "hours_ago": 2},
        {"headline": "Iran warns it may close Hormuz strait after strikes", "source": "B", "hours_ago": 3},
        {"headline": "Iran could reportedly resume talks, sources say", "source": "C", "hours_ago": 5,
         "info_type": "Speculation / unconfirmed"},
        {"headline": "Iran oil exports fall", "source": "D", "hours_ago": 24 * 15},
    ])
    tagged = geo.tag_news(df)
    att = geo.attention(tagged, NOW).set_index("key")
    assert att.loc["iran", "Stories 7d"] == 3
    # collection just started → no trend claim, however many stories there are
    assert att.loc["iran", "Attention ratio"] is None and att.loc["iran", "Trend"] == "Building baseline"
    att2 = geo.attention(tagged, NOW, since=NOW - timedelta(days=40)).set_index("key")
    assert att2.loc["iran", "Trend"] == "Too few prior stories"          # only 1 prior story < MIN_BASE_STORIES
    cards = geo.event_cards(tagged, "iran", NOW, days=7)
    assert len(cards) == 2
    corroborated = next(c for c in cards if "Hormuz" in c["headline"])
    assert "2 independent" in corroborated["confirmed"] and "Iran" in corroborated["who"]
    spec = next(c for c in cards if "talks" in c["headline"])
    assert "Single-source" in spec["confirmed"] and "speculative" in spec["uncertain"]
    assert spec["why_it_matters_framework"] == geo.THEATER_BY_KEY["iran"].channels


def test_market_reaction_marks_missing():
    from tradingos.intel.geopolitics import market_reaction
    snap = pd.DataFrame([{"Symbol": "BZ=F", "Name": "Brent", "Last": 80.0, "1D %": 1.0, "1W %": 2.0, "1M %": 3.0,
                          "Last bar": "2026-11-24", "Freshness": "Current"}])
    mr = market_reaction(snap, "iran")
    assert mr.loc[mr["Symbol"] == "BZ=F", "1W %"].iloc[0] == 2.0
    assert (mr["Freshness"] == "not in market snapshot").sum() >= 1


def test_geo_empty():
    from tradingos.intel import geopolitics as geo
    tagged = geo.tag_news(pd.DataFrame())
    assert geo.attention(tagged, NOW)["Stories 7d"].sum() == 0
    assert geo.event_cards(tagged, "iran", NOW) == []
    assert geo.timeline(tagged, NOW).empty


# ----------------------------------------------------------------------------- entities
def test_entities():
    from tradingos.intel.entities import extract
    e = extract("RBI holds repo rate as Fed chair Powell warns; Beijing responds to US tariffs")
    assert "RBI" in e["institutions"] and "Federal Reserve" in e["institutions"]
    assert "China" in e["countries"]
    assert "Ukraine" not in extract("Bank results beat estimates")["countries"]


# ----------------------------------------------------------------------------- trends
def _m(**kw):
    base = {"rs_1M": 0.0, "rs_3M": 0.0, "rs_6M": 0.0, "pct_from_200dma": 5.0, "rsi14": 55.0,
            "above_50dma": True, "above_200dma": True}
    return {**base, **kw}


@pytest.mark.parametrize("metrics,attn,stage", [
    (_m(rs_1M=4, rs_3M=12, rs_6M=20, pct_from_200dma=28), None, "Crowded"),
    (_m(rs_1M=-4, rs_3M=5, rs_6M=10), None, "Weakening"),
    (_m(rs_1M=3, rs_3M=6, rs_6M=-2), None, "Gaining momentum"),
    (_m(rs_1M=0.5, rs_3M=6, rs_6M=8), None, "Established"),
    (_m(rs_1M=2, rs_3M=-5, rs_6M=-8, above_50dma=True), None, "Emerging"),
    (_m(rs_1M=-1, rs_3M=-5, rs_6M=-8), None, "Out of favour"),
    (_m(rs_1M=0.5, rs_3M=3, rs_6M=-1, above_200dma=False), 1.6, "Gaining momentum"),
])
def test_trend_classification(metrics, attn, stage):
    from tradingos.intel.trends import classify
    assert classify(metrics, attn)[0] == stage


def test_classify_missing_data():
    from tradingos.intel.trends import classify
    assert classify({"error": "no data"}, None)[0] == "No clear trend"
    assert classify(_m(rs_1M=None), None)[0] == "No clear trend"


def test_theme_metrics_and_basket():
    from tradingos.intel.trends import basket_index, theme_metrics
    up = make_ohlcv(100 * np.exp(np.linspace(0, 0.5, 300)))
    flat = make_ohlcv(np.full(300, 100.0))
    frames = {"AAA": up, "BBB": up, "^GSPC": flat}
    idx = basket_index(frames, ["AAA", "BBB"])
    assert idx.iloc[-1] > idx.iloc[0]
    m = theme_metrics({"proxies": ["AAA"], "companies": ["BBB", "ZZZ"], "benchmark": "^GSPC"}, frames)
    assert m["basket_basis"] == "proxies" and m["rs_3M"] > 0 and m["breadth_above_50dma_pct"] == 100
    m2 = theme_metrics({"proxies": ["NOPE"], "companies": ["BBB"], "benchmark": "^GSPC"}, frames)
    assert m2["basket_basis"] == "companies"
    assert "error" in theme_metrics({"proxies": [], "companies": [], "benchmark": "^GSPC"}, frames)


def test_themes_config_valid():
    from tradingos.intel.trends import load_themes
    themes = load_themes()
    assert len(themes) >= 25
    for t in themes:
        assert t["benchmark"] in ("^GSPC", "^NSEI")
        assert t["proxies"] or t["companies"]
        assert t["keywords"] and t["invalidation"]


def test_news_attention_requires_baseline():
    from tradingos.intel.trends import news_attention
    rows = [{"headline": "Uranium prices jump", "source": "A", "hours_ago": 5},
            {"headline": "Uranium miners rally", "source": "B", "hours_ago": 30}]
    rows += [{"headline": f"Uranium supply update {i}", "source": "C", "hours_ago": 24 * (9 + 4 * i)} for i in range(4)]
    df = _news(rows)
    young = news_attention({"keywords": ["uranium"]}, df.assign(retrieved_utc=NOW - timedelta(days=2)), NOW)
    assert young["stories_7d"] == 2 and young["attention_ratio"] is None and not young["baseline_ready"]
    old = news_attention({"keywords": ["uranium"]}, df.assign(retrieved_utc=NOW - timedelta(days=60)), NOW)
    assert old["baseline_ready"] and old["attention_ratio"] == pytest.approx(2.0)   # 2 vs 4/4 per week


def test_attention_ratio_with_real_baseline():
    from tradingos.intel import geopolitics as geo
    rows = [{"headline": f"Taiwan strait tension item {i}", "source": f"S{i}", "hours_ago": 10 + i} for i in range(6)]
    rows += [{"headline": f"Taiwan update number {i}", "source": "Z", "hours_ago": 24 * (8 + 5 * i)} for i in range(4)]
    att = geo.attention(geo.tag_news(_news(rows)), NOW, since=NOW - timedelta(days=50)).set_index("key")
    assert att.loc["taiwan", "Attention ratio"] == pytest.approx(6.0) and att.loc["taiwan", "Trend"] == "Rising"


# ----------------------------------------------------------------------------- threads
def test_threads():
    from tradingos.intel.news_rank import threads
    df = _news([
        {"headline": "Nvidia shares soar 31% as Jensen Huang's return sparks Wall Street rally", "source": "A", "hours_ago": 1},
        {"headline": "Tech stocks see monster rally after Jensen Huang returns as Nvidia CEO", "source": "B", "hours_ago": 6},
        {"headline": "Brazil coffee harvest forecast trimmed", "source": "C", "hours_ago": 2},
    ])
    th = threads(df, now=NOW)
    assert len(th) == 1 and th.iloc[0]["n_sources"] == 2 and th.iloc[0]["span_hours"] == 5.0
    assert len(th.iloc[0]["timeline"]) == 2


# ----------------------------------------------------------------------------- migration of econ_events
def test_econ_event_new_columns(tmp_path):
    import sqlite3
    from tradingos.db.models import TradingBase
    from tradingos.db.session import add_missing_columns, make_engine
    p = tmp_path / "old.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE econ_events (id INTEGER PRIMARY KEY, event_date DATE, title VARCHAR(256))")
    added = add_missing_columns(make_engine(p), TradingBase)
    assert {"econ_events.country", "econ_events.event_time"} <= set(added)


def test_economic_calendar_offline(monkeypatch):
    """No FRED key and the Fed site unreachable: manual events still show, errors are explicit."""
    import requests
    from tradingos.db.models import EconEvent
    from tradingos.db.session import session_scope
    from tradingos.intel import calendars
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")))
    with session_scope() as s:
        s.add(EconEvent(event_date=date.today() + timedelta(days=2), title="RBI MPC decision", importance="high",
                        source_url="https://www.rbi.org.in", country="IN", event_time="10:00 IST"))
    df, errs = calendars.economic_calendar()
    assert any("FRED" in e for e in errs) and any("FOMC" in e for e in errs)
    assert list(df["event"]) == ["RBI MPC decision"] and df["country"].iloc[0] == "IN"
