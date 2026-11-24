import numpy as np

from tradingos.analysis.technical import analyze, classify_trend, explain, find_pivots, suggest_levels, support_resistance
from tests.conftest import make_ohlcv


def zigzag(n=260):
    x = np.arange(n)
    return 100 + 10 * np.sin(x / 8) + x * 0.05


def test_pivots_and_levels_come_from_data():
    df = make_ohlcv(zigzag())
    highs, lows = find_pivots(df, 5)
    assert len(highs) > 3 and len(lows) > 3
    sup, res = support_resistance(df)
    price = df["Close"].iloc[-1]
    assert all(s.price < price for s in sup)
    assert all(r.price > price for r in res)
    lo, hi = df["Low"].min(), df["High"].max()
    for lvl in sup + res:
        assert lo <= lvl.price <= hi  # never invented outside traded range


def test_analyze_short_history():
    out = analyze(make_ohlcv(np.full(10, 5.0)))
    assert "error" in out


def test_analyze_uptrend(uptrend):
    s = analyze(uptrend, None)
    assert s["above_sma200"] and s["above_sma50"]
    assert "uptrend" in s["trend"].lower()
    assert s["rs_vs_spy_pp"] is None  # no benchmark supplied → no fabricated RS


def test_classify_trend():
    assert classify_trend(110, 105, 100, 90, 1.0) == "Strong uptrend"
    assert classify_trend(80, 85, 90, 100, -1.0) == "Downtrend"
    assert "insufficient" in classify_trend(10, None, None, None, None).lower()


def test_suggest_levels_long_geometry(uptrend):
    s = analyze(uptrend, None)
    for setup in ("Breakout", "Pullback", "Momentum"):
        lv = suggest_levels(s, setup)
        assert lv["stop"] < lv["entry"] < lv["target1"] <= lv["target2"]
        assert lv["stop_basis"] and lv["target1_basis"]


def test_explain_has_nine_points(uptrend):
    e = explain(analyze(uptrend, None))
    assert len(e) == 9
