"""US macro data from FRED (Federal Reserve Bank of St. Louis).

Works without a key via the public CSV endpoint; uses the official API if FRED_API_KEY is set.
All transforms (YoY, MoM, changes) are computed here in Python.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from tradingos.config import load_config
from tradingos.data import cache
from tradingos.data.base import DataResult, Freshness

log = logging.getLogger(__name__)
SOURCE = "FRED, Federal Reserve Bank of St. Louis"


@dataclass(frozen=True)
class MacroSeries:
    sid: str
    label: str
    group: str
    transform: str  # level | yoy | mom | diff
    unit: str


MACRO_SERIES: list[MacroSeries] = [
    MacroSeries("DFEDTARU", "Fed funds target (upper)", "Fed & rates", "level", "%"),
    MacroSeries("DGS2", "2Y Treasury yield", "Fed & rates", "level", "%"),
    MacroSeries("DGS10", "10Y Treasury yield", "Fed & rates", "level", "%"),
    MacroSeries("T10Y2Y", "10Y–2Y spread", "Fed & rates", "level", "pp"),
    MacroSeries("CPIAUCSL", "CPI inflation (YoY)", "Inflation", "yoy", "%"),
    MacroSeries("CPILFESL", "Core CPI (YoY)", "Inflation", "yoy", "%"),
    MacroSeries("PCEPI", "PCE inflation (YoY)", "Inflation", "yoy", "%"),
    MacroSeries("PCEPILFE", "Core PCE (YoY)", "Inflation", "yoy", "%"),
    MacroSeries("UNRATE", "Unemployment rate", "Labour", "level", "%"),
    MacroSeries("PAYEMS", "Nonfarm payrolls (m/m change)", "Labour", "diff", "k jobs"),
    MacroSeries("ICSA", "Initial jobless claims", "Labour", "level", "claims"),
    MacroSeries("A191RL1Q225SBEA", "Real GDP growth (q/q annualised)", "Growth", "level", "%"),
    MacroSeries("RSAFS", "Retail sales (m/m)", "Consumer", "mom", "%"),
    MacroSeries("PCEC96", "Real consumer spending (m/m)", "Consumer", "mom", "%"),
    MacroSeries("UMCSENT", "UMich consumer sentiment", "Consumer", "level", "index"),
    MacroSeries("SAHMREALTIME", "Sahm rule recession indicator", "Recession risk", "level", "pp"),
    MacroSeries("BAMLH0A0HYM2", "High-yield credit spread", "Recession risk", "level", "%"),
]

_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"


def _fetch_fred(sid: str, start: date) -> pd.Series | None:
    cfg = load_config()
    if cfg.fred_api_key:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": sid, "api_key": cfg.fred_api_key, "file_type": "json",
                                 "observation_start": start.isoformat()}, timeout=30)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        s = pd.Series({pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce") for o in obs})
    else:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                         params={"id": sid, "cosd": start.isoformat()},
                         headers={"User-Agent": _BROWSER_UA}, timeout=45)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
        s = pd.Series(pd.to_numeric(df["value"], errors="coerce").values, index=pd.to_datetime(df["date"]))
    s = s.dropna()
    return s if len(s) else None


def apply_transform(s: pd.Series, transform: str) -> pd.Series:
    if transform == "yoy":
        return (s / s.shift(12) - 1) * 100
    if transform == "mom":
        return (s / s.shift(1) - 1) * 100
    if transform == "diff":
        return s.diff()
    return s


def get_series(ms: MacroSeries, years: int = 4, force: bool = False) -> DataResult[pd.Series]:
    start = date.today() - timedelta(days=365 * years)
    try:
        raw = cache.cached(f"fred|{ms.sid}|{start.year}", 6 * 3600, lambda: _fetch_fred(ms.sid, start), force=force)
    except Exception as e:
        log.warning("FRED %s failed: %s", ms.sid, e)
        return DataResult(None, SOURCE, error=f"{ms.sid}: {e}", missing=[ms.sid])
    if raw is None:
        return DataResult(None, SOURCE, error=f"{ms.sid}: no data", missing=[ms.sid])
    s = apply_transform(raw, ms.transform).dropna()
    return DataResult(s, SOURCE, as_of=s.index[-1].date() if len(s) else None, freshness=Freshness.STATIC,
                      notes=f"https://fred.stlouisfed.org/series/{ms.sid}")


def macro_snapshot(force: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Latest value, prior value and change for each series. Returns (table, errors)."""
    rows, errors = [], []
    for ms in MACRO_SERIES:
        res = get_series(ms, force=force)
        if not res.ok or len(res.data) < 2:
            errors.append(res.error or f"{ms.sid}: insufficient history")
            continue
        s = res.data
        rows.append({
            "Group": ms.group, "Indicator": ms.label, "Latest": round(float(s.iloc[-1]), 2),
            "Previous": round(float(s.iloc[-2]), 2), "Change": round(float(s.iloc[-1] - s.iloc[-2]), 2),
            "Unit": ms.unit, "Observation date": s.index[-1].date().isoformat(), "Series": ms.sid,
            "Source": f"https://fred.stlouisfed.org/series/{ms.sid}",
        })
    df = pd.DataFrame(rows)
    df.attrs["retrieved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return df, errors


def recession_signals(snap: pd.DataFrame) -> list[str]:
    """Deterministic, transparent flags — not a forecast."""
    if snap.empty:
        return []
    v = dict(zip(snap["Series"], snap["Latest"]))
    out = []
    if "SAHMREALTIME" in v:
        out.append(f"Sahm rule at {v['SAHMREALTIME']:.2f} ({'≥0.50 — historically associated with recession onset' if v['SAHMREALTIME'] >= 0.5 else 'below the 0.50 trigger'}).")
    if "T10Y2Y" in v:
        out.append(f"10Y–2Y curve {v['T10Y2Y']:+.2f}pp ({'inverted' if v['T10Y2Y'] < 0 else 'positively sloped'}).")
    if "BAMLH0A0HYM2" in v:
        hy = v["BAMLH0A0HYM2"]
        out.append(f"HY credit spread {hy:.2f}% ({'elevated stress (>5%)' if hy > 5 else 'not signalling acute stress'}).")
    return out
