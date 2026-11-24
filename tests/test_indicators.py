import numpy as np
import pandas as pd
import pytest

from tradingos.analysis import indicators as ind
from tests.conftest import make_ohlcv


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(s, 3)
    assert out.isna().sum() == 2
    assert out.iloc[-1] == pytest.approx(4.0)


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up).iloc[-1] == pytest.approx(100.0)
    flat = pd.Series(np.full(60, 10.0))
    assert ind.rsi(flat).iloc[-1] == pytest.approx(50.0)
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(down).iloc[-1] == pytest.approx(0.0)


def test_rsi_matches_wilder_manual():
    closes = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03,
                        45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64])
    d = closes.diff().dropna()
    g, l_ = d.clip(lower=0), -d.clip(upper=0)
    ag, al = g.iloc[:14].mean(), l_.iloc[:14].mean()
    # pandas ewm(adjust=False) seeds with the first value rather than the SMA; compare the recursive form
    ag2, al2 = g.iloc[0], l_.iloc[0]
    for gi, li in zip(g.iloc[1:], l_.iloc[1:]):
        ag2 = ag2 + (gi - ag2) / 14
        al2 = al2 + (li - al2) / 14
    expected = 100 - 100 / (1 + ag2 / al2)
    assert ind.rsi(closes).iloc[-1] == pytest.approx(expected, rel=1e-9)
    assert 0 < expected < 100 and ag > 0 and al > 0


def test_atr_constant_range():
    df = make_ohlcv(np.full(40, 100.0), spread=0.01)  # high-low = 2.0 each bar
    assert ind.atr(df).iloc[-1] == pytest.approx(2.0, rel=1e-6)


def test_macd_positive_in_uptrend(uptrend):
    m = ind.macd(uptrend["Close"])
    assert m["macd"].iloc[-1] > 0


def test_relative_volume_uses_prior_window():
    v = pd.Series([100.0] * 20 + [300.0])
    assert ind.relative_volume(v).iloc[-1] == pytest.approx(3.0)


def test_returns_and_relative_strength():
    a = pd.Series([100.0, 110.0, 121.0])
    b = pd.Series([100.0, 100.0, 105.0])
    assert ind.pct_return(a, 2) == pytest.approx(21.0)
    assert ind.relative_strength(a, b, 2) == pytest.approx(16.0)
    assert ind.pct_return(a, 5) is None


def test_weekly_resample(uptrend):
    w = ind.to_weekly(uptrend)
    assert len(w) < len(uptrend)
    assert (w["High"] >= w["Low"]).all()


def test_finite():
    assert ind.finite(float("nan")) is None
    assert ind.finite("x") is None
    assert ind.finite(2) == 2.0
