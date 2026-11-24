"""Gold intelligence: driver attribution, CFTC positioning, INR conversion.

Everything here is arithmetic on sourced series:
  * Gold, DXY, USD/INR, silver — Yahoo Finance daily bars (delayed).
  * Real yield (10Y TIPS, DFII10), 10Y breakeven inflation (T10YIE) — FRED.
  * Managed-money positioning — CFTC Commitments of Traders (disaggregated, futures only), public Socrata API.
Driver "readings" are rule-based: they say which known drivers moved in a gold-supportive or gold-negative
direction over the window, and how gold's daily returns have correlated with each recently. They do not
claim causation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from tradingos.data import cache
from tradingos.data.base import DataResult, Freshness
from tradingos.data.macro import MacroSeries, get_series

log = logging.getLogger(__name__)

TROY_OZ_G = 31.1034768
REAL_YIELD = MacroSeries("DFII10", "10Y real yield (TIPS)", "Gold drivers", "level", "%")
BREAKEVEN = MacroSeries("T10YIE", "10Y breakeven inflation", "Gold drivers", "level", "%")
NOMINAL_10Y = MacroSeries("DGS10", "10Y Treasury yield", "Gold drivers", "level", "%")
CFTC_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CFTC_SOURCE = "CFTC Commitments of Traders (disaggregated, futures only)"
CFTC_CODES = {"Gold (COMEX)": "088691", "Silver (COMEX)": "084691", "Copper (COMEX)": "085692",
              "WTI crude (NYMEX)": "067651"}


def _window_change(s: pd.Series | None, days: int) -> float | None:
    """Change over the last `days` calendar days (level units)."""
    if s is None or len(s) < 2:
        return None
    s = s.dropna()
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= cutoff]
    if past.empty:
        return None
    return float(s.iloc[-1] - past.iloc[-1])


def _window_pct(s: pd.Series | None, days: int) -> float | None:
    if s is None or len(s) < 2:
        return None
    s = s.dropna()
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= cutoff]
    if past.empty or past.iloc[-1] == 0:
        return None
    return float(s.iloc[-1] / past.iloc[-1] - 1) * 100


def rolling_corr(a: pd.Series, b: pd.Series, window: int = 60, diff_b: bool = False) -> float | None:
    """Correlation of gold % returns with driver % returns (or level changes when diff_b)."""
    ra = a.pct_change()
    rb = b.diff() if diff_b else b.pct_change()
    j = pd.concat([ra, rb], axis=1, join="inner").dropna().tail(window)
    if len(j) < window // 2:
        return None
    c = j.iloc[:, 0].corr(j.iloc[:, 1])
    return None if pd.isna(c) else round(float(c), 2)


def driver_table(gold: pd.Series, dxy: pd.Series | None, real: pd.Series | None, be: pd.Series | None,
                 window_days: int = 30) -> list[dict]:
    """For each driver: change over window, whether that move is conventionally gold-supportive, 60d correlation."""
    out = []
    if dxy is not None:
        ch = _window_pct(dxy, window_days)
        out.append({"Driver": "US dollar (DXY)", "Change": None if ch is None else f"{ch:+.2f}%",
                    "Conventional effect on gold": None if ch is None else ("supportive" if ch < 0 else "negative"),
                    "60d corr with gold": rolling_corr(gold, dxy),
                    "Why it matters": "Gold is priced in USD; a weaker dollar makes it cheaper for non-US buyers."})
    if real is not None:
        ch = _window_change(real, window_days)
        out.append({"Driver": "10Y real yield (TIPS)", "Change": None if ch is None else f"{ch * 100:+.0f} bp",
                    "Conventional effect on gold": None if ch is None else ("supportive" if ch < 0 else "negative"),
                    "60d corr with gold": rolling_corr(gold, real, diff_b=True),
                    "Why it matters": "Gold pays no yield; higher real yields raise the opportunity cost of holding it."})
    if be is not None:
        ch = _window_change(be, window_days)
        out.append({"Driver": "10Y breakeven inflation", "Change": None if ch is None else f"{ch * 100:+.0f} bp",
                    "Conventional effect on gold": None if ch is None else ("supportive" if ch > 0 else "negative"),
                    "60d corr with gold": rolling_corr(gold, be, diff_b=True),
                    "Why it matters": "Rising inflation expectations increase demand for real-asset hedges."})
    return out


def attribution_reading(gold_chg_pct: float | None, drivers: list[dict]) -> str:
    """Plain-language, rule-based summary of which drivers are consistent with gold's move."""
    if gold_chg_pct is None:
        return "Gold change unavailable."
    direction = "up" if gold_chg_pct > 0 else "down"
    want = "supportive" if gold_chg_pct > 0 else "negative"
    consistent = [d["Driver"] for d in drivers if d.get("Conventional effect on gold") == want]
    against = [d["Driver"] for d in drivers if d.get("Conventional effect on gold") not in (None, want)]
    msg = f"Gold is {direction} {abs(gold_chg_pct):.1f}% over the window. "
    if consistent:
        msg += f"Moves consistent with that: {', '.join(consistent)}. "
    if against:
        msg += (f"Moving the other way: {', '.join(against)} — when macro drivers do not explain the move, "
                "investment/central-bank demand or geopolitical hedging are common candidates (not measured here). ")
    if not consistent and not against:
        msg += "No driver data available. "
    return msg.strip()


def inr_per_10g(gold_usd_oz: float | None, usdinr: float | None) -> float | None:
    """International gold converted to INR / 10 g. Excludes import duty, GST and local premium — NOT an MCX price."""
    if not gold_usd_oz or not usdinr:
        return None
    return round(gold_usd_oz * usdinr / TROY_OZ_G * 10, 0)


def macro_drivers(force: bool = False) -> dict[str, DataResult]:
    return {k: get_series(ms, years=3, force=force) for k, ms in
            (("real_yield", REAL_YIELD), ("breakeven", BREAKEVEN), ("nominal_10y", NOMINAL_10Y))}


def cftc_positioning(code: str, weeks: int = 52, force: bool = False) -> DataResult[pd.DataFrame]:
    """Weekly managed-money net positioning for a CFTC contract code."""
    def fetch():
        r = requests.get(CFTC_URL, params={"$where": f"cftc_contract_market_code='{code}'",
                                           "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": weeks,
                                           "$select": "report_date_as_yyyy_mm_dd,open_interest_all,"
                                                      "m_money_positions_long_all,m_money_positions_short_all,"
                                                      "prod_merc_positions_long,prod_merc_positions_short"},
                         timeout=30)
        r.raise_for_status()
        return r.json()
    try:
        raw = cache.cached(f"cftc|{code}|{weeks}", 12 * 3600, fetch, force=force)
    except Exception as e:
        return DataResult(None, CFTC_SOURCE, error=f"CFTC request failed: {e}")
    if not raw:
        return DataResult(None, CFTC_SOURCE, error="CFTC returned no rows")
    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).dt.date
    for c in ("open_interest_all", "m_money_positions_long_all", "m_money_positions_short_all",
              "prod_merc_positions_long", "prod_merc_positions_short"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["mm_net"] = df["m_money_positions_long_all"] - df["m_money_positions_short_all"]
    df["mm_net_pct_oi"] = (df["mm_net"] / df["open_interest_all"] * 100).round(1)
    df = df.sort_values("date").reset_index(drop=True)
    last = df["date"].iloc[-1]
    return DataResult(df[["date", "open_interest_all", "m_money_positions_long_all", "m_money_positions_short_all",
                          "mm_net", "mm_net_pct_oi"]], CFTC_SOURCE, as_of=last, freshness=Freshness.STATIC,
                      notes="Positions as of Tuesday, published the following Friday. https://www.cftc.gov/MarketReports/CommitmentsofTraders")


def positioning_summary(df: pd.DataFrame) -> dict:
    """Latest net, weekly change and percentile within the window (crowding gauge)."""
    if df is None or df.empty:
        return {}
    net = df["mm_net"]
    last = float(net.iloc[-1])
    pctile = round(float((net <= last).mean() * 100), 0)
    return {"as_of": str(df["date"].iloc[-1]), "mm_net": int(last),
            "weekly_change": int(last - net.iloc[-2]) if len(net) >= 2 else None,
            "net_pct_open_interest": float(df["mm_net_pct_oi"].iloc[-1]),
            "percentile_in_window": pctile, "weeks_in_window": len(df),
            "reading": ("Crowded long (top decile of the window)" if pctile >= 90 else
                        "Light positioning (bottom decile)" if pctile <= 10 else "Within normal range")}


def gold_context(snap: pd.DataFrame, closes: dict[str, pd.Series], force: bool = False) -> dict:
    """Assemble the gold intelligence payload used by the page and briefings."""
    from tradingos.intel.markets import row
    gold = closes.get("GC=F")
    drivers = macro_drivers(force=force)
    real = drivers["real_yield"].data if drivers["real_yield"].ok else None
    be = drivers["breakeven"].data if drivers["breakeven"].ok else None
    dxy = closes.get("DX-Y.NYB")
    out: dict = {"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                 "errors": [r.error for r in drivers.values() if r.error]}
    g, s, inr = row(snap, "GC=F"), row(snap, "SI=F"), row(snap, "INR=X")
    out["gold"] = {k: g.get(k) for k in ("Last", "1D %", "1W %", "1M %", "3M %", "YTD %", "1Y %", "Last bar",
                                         "Freshness", "Above 200DMA")} if g else None
    if g and s and s.get("Last"):
        out["gold_silver_ratio"] = round(g["Last"] / s["Last"], 1)
    if g and inr:
        out["gold_inr_per_10g"] = {"value": inr_per_10g(g["Last"], inr["Last"]),
                                   "basis": f"COMEX front-month × USD/INR ÷ 31.1035 × 10 (gold bar {g['Last bar']}, "
                                            f"FX bar {inr['Last bar']}). Excludes import duty, GST and local premium; "
                                            "not the MCX price."}
    if gold is not None and len(gold) > 60:
        short = driver_table(gold, dxy, real, be, window_days=30)
        out["drivers_1m"] = short
        out["reading_1m"] = attribution_reading(_window_pct(gold, 30), short)
        long_ = driver_table(gold, dxy, real, be, window_days=365)
        out["drivers_1y"] = long_
        out["reading_1y"] = attribution_reading(_window_pct(gold, 365), long_)
        s200 = gold.rolling(200).mean().iloc[-1] if len(gold) >= 200 else None
        out["structure"] = {
            "above_200dma": None if s200 is None or pd.isna(s200) else bool(gold.iloc[-1] > s200),
            "pct_from_200dma": None if s200 is None or pd.isna(s200) else round(float(gold.iloc[-1] / s200 - 1) * 100, 1),
            "pct_from_52w_high": round(float(gold.iloc[-1] / gold.tail(252).max() - 1) * 100, 1),
        }
    for key, ms_res in (("real_yield_10y", drivers["real_yield"]), ("breakeven_10y", drivers["breakeven"])):
        if ms_res.ok and len(ms_res.data):
            out[key] = {"value": round(float(ms_res.data.iloc[-1]), 2), "as_of": str(ms_res.as_of),
                        "source": ms_res.notes}
    pos = cftc_positioning(CFTC_CODES["Gold (COMEX)"], force=force)
    if pos.ok:
        out["cftc_gold"] = positioning_summary(pos.data)
    else:
        out["errors"].append(pos.error)
    return out
