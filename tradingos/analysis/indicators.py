"""Deterministic technical indicators (pure pandas/numpy, fully unit-tested).

Conventions: input is an OHLCV DataFrame indexed by date with columns
Open, High, Low, Close, Volume. RSI and ATR use Wilder's smoothing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    out = out.where(avg_loss != 0, 100.0)                       # no losses → RSI 100
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)  # flat → 50
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def relative_volume(volume: pd.Series, n: int = 20) -> pd.Series:
    """Today's volume divided by the average of the PRIOR n sessions."""
    return volume / volume.shift(1).rolling(n, min_periods=n).mean()


def pct_return(close: pd.Series, n: int) -> float | None:
    if len(close) <= n or close.iloc[-n - 1] == 0:
        return None
    return float(close.iloc[-1] / close.iloc[-n - 1] - 1) * 100


def relative_strength(close: pd.Series, bench: pd.Series, n: int = 63) -> float | None:
    """Excess return vs benchmark over n sessions, in percentage points."""
    a, b = pct_return(close, n), pct_return(bench.reindex(close.index).ffill(), n)
    return None if a is None or b is None else a - b


def rs_line(close: pd.Series, bench: pd.Series) -> pd.Series:
    b = bench.reindex(close.index).ffill()
    line = close / b
    return line / line.dropna().iloc[0] * 100 if line.notna().any() else line


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df.resample("W-FRI").agg(agg).dropna(subset=["Close"])


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with standard indicator columns appended."""
    out = df.copy()
    c = out["Close"]
    for n in (20, 50, 100, 200):
        out[f"SMA{n}"] = sma(c, n)
    out["RSI14"] = rsi(c)
    m = macd(c)
    out["MACD"], out["MACD_signal"], out["MACD_hist"] = m["macd"], m["signal"], m["hist"]
    out["ATR14"] = atr(out)
    out["RelVol20"] = relative_volume(out["Volume"])
    out["AvgDollarVol20"] = (c * out["Volume"]).rolling(20, min_periods=20).mean()
    return out


def slope(s: pd.Series, n: int = 10) -> float | None:
    """% change of a series over the last n points (used for MA direction)."""
    s = s.dropna()
    if len(s) <= n or s.iloc[-n - 1] == 0:
        return None
    return float(s.iloc[-1] / s.iloc[-n - 1] - 1) * 100


def finite(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None
