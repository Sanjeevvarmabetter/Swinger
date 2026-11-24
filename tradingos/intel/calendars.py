"""Event calendars from sources this account can actually access (verified 2026-11-24):

  * US economic release DATES — FRED `releases/dates` (official schedule; no forecasts/actuals).
  * Earnings — Finnhub `calendar/earnings` (free tier), FMP `earnings-calendar` as fallback.
  * IPOs — Finnhub `calendar/ipo`.
  * Manually entered events (FOMC, RBI MPC, etc.) — the existing econ_events table.

NOT available on the current plans: Finnhub economic calendar (403), FMP economic calendar / IPO
calendar (402). Forecast and consensus values for macro releases are therefore never shown.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from sqlalchemy import select

from tradingos.config import load_config
from tradingos.data import cache
from tradingos.data.base import DataResult, Freshness

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")

# FRED release id → (label, importance, usual ET release time per the publishing agency's schedule)
US_RELEASES: dict[int, tuple[str, str, time | None]] = {
    10: ("US CPI (BLS)", "high", time(8, 30)),
    46: ("US PPI (BLS)", "medium", time(8, 30)),
    50: ("US jobs report — NFP & unemployment (BLS)", "high", time(8, 30)),
    53: ("US GDP (BEA)", "high", time(8, 30)),
    54: ("US PCE inflation & spending (BEA)", "high", time(8, 30)),
    9: ("US retail sales (Census)", "medium", time(8, 30)),
    192: ("US JOLTS job openings (BLS)", "medium", time(10, 0)),
    180: ("US weekly jobless claims (DOL)", "low", time(8, 30)),
    13: ("US industrial production (Fed G.17)", "low", time(9, 15)),
}


def to_ist(d: date, t: time | None, tz: ZoneInfo = ET) -> str:
    if t is None:
        return "time n/a"
    return datetime.combine(d, t, tzinfo=tz).astimezone(IST).strftime("%a %d %b %H:%M IST")


def us_release_calendar(days: int = 21, force: bool = False) -> DataResult[pd.DataFrame]:
    cfg = load_config()
    src = "FRED release calendar (St. Louis Fed)"
    if not cfg.fred_api_key:
        return DataResult(None, src, error="FRED_API_KEY not set — release calendar needs the FRED API.")
    start = date.today()
    end = start + timedelta(days=days)

    def fetch():
        r = requests.get("https://api.stlouisfed.org/fred/releases/dates",
                         params={"api_key": cfg.fred_api_key, "file_type": "json", "realtime_start": start.isoformat(),
                                 "realtime_end": end.isoformat(), "include_release_dates_with_no_data": "true",
                                 "limit": 1000, "sort_order": "asc"}, timeout=30)
        r.raise_for_status()
        return r.json().get("release_dates", [])
    try:
        raw = cache.cached(f"fred_rel|{start}|{days}", 6 * 3600, fetch, force=force)
    except Exception as e:
        return DataResult(None, src, error=f"FRED release calendar failed: {e}")
    rows = []
    for r in raw or []:
        rid = r.get("release_id")
        if rid not in US_RELEASES:
            continue
        label, imp, t = US_RELEASES[rid]
        d = pd.Timestamp(r["date"]).date()
        rows.append({"date": d, "event": label, "country": "US", "importance": imp,
                     "time_ist": to_ist(d, t) + (" (usual time)" if t else ""),
                     "previous": None, "forecast": None, "actual": None,
                     "source": f"https://fred.stlouisfed.org/release?rid={rid}"})
    df = pd.DataFrame(rows).drop_duplicates(["date", "event"]) if rows else pd.DataFrame(
        columns=["date", "event", "country", "importance", "time_ist", "source"])
    return DataResult(df, src, as_of=date.today(), freshness=Freshness.CURRENT,
                      notes="Official scheduled release dates. Forecasts/consensus are not available on current "
                            "data plans and are never estimated.")


def manual_events(days: int = 21) -> pd.DataFrame:
    """User-entered events (FOMC, RBI MPC, ECB, etc.) from the econ_events table."""
    from tradingos.db.models import EconEvent
    from tradingos.db.session import session_scope
    today = date.today()
    with session_scope() as s:
        rows = s.scalars(select(EconEvent).where(EconEvent.event_date >= today,
                                                 EconEvent.event_date <= today + timedelta(days=days))
                         .order_by(EconEvent.event_date)).all()
        return pd.DataFrame([{"date": r.event_date, "event": r.title, "country": "", "importance": r.importance,
                              "time_ist": "", "source": r.source_url or "manual entry"} for r in rows])


def earnings_calendar(days: int = 7, symbols: set[str] | None = None, force: bool = False) -> DataResult[pd.DataFrame]:
    """Upcoming earnings, optionally filtered to `symbols`. Finnhub first, FMP fallback."""
    cfg = load_config()
    start, end = date.today(), date.today() + timedelta(days=days)
    errors = []
    if cfg.finnhub_api_key:
        def fh():
            r = requests.get("https://finnhub.io/api/v1/calendar/earnings",
                             params={"from": start.isoformat(), "to": end.isoformat(), "token": cfg.finnhub_api_key},
                             timeout=30)
            r.raise_for_status()
            return r.json().get("earningsCalendar", [])
        try:
            raw = cache.cached(f"fh_earn|{start}|{days}", 6 * 3600, fh, force=force)
            df = pd.DataFrame([{"date": pd.Timestamp(e["date"]).date(), "symbol": e.get("symbol"),
                                "when": {"bmo": "before open", "amc": "after close", "dmh": "during hours"}.get(e.get("hour") or "", ""),
                                "eps_estimate": e.get("epsEstimate"), "revenue_estimate": e.get("revenueEstimate")}
                               for e in raw or []])
            if symbols is not None and len(df):
                df = df[df["symbol"].isin(symbols)]
            return DataResult(df.sort_values("date").reset_index(drop=True) if len(df) else df,
                              "Finnhub earnings calendar", as_of=start, freshness=Freshness.CURRENT,
                              notes="Dates and estimates from Finnhub; confirm on company IR pages.")
        except Exception as e:
            errors.append(f"Finnhub: {e}")
    if cfg.fmp_api_key:
        def fmp():
            r = requests.get("https://financialmodelingprep.com/stable/earnings-calendar",
                             params={"from": start.isoformat(), "to": end.isoformat(), "apikey": cfg.fmp_api_key},
                             timeout=30)
            r.raise_for_status()
            return r.json()
        try:
            raw = cache.cached(f"fmp_earn|{start}|{days}", 6 * 3600, fmp, force=force)
            df = pd.DataFrame([{"date": pd.Timestamp(e["date"]).date(), "symbol": e.get("symbol"), "when": "",
                                "eps_estimate": e.get("epsEstimated"), "revenue_estimate": e.get("revenueEstimated")}
                               for e in raw or []])
            if symbols is not None and len(df):
                df = df[df["symbol"].isin(symbols)]
            return DataResult(df.sort_values("date").reset_index(drop=True) if len(df) else df,
                              "FMP earnings calendar", as_of=start, freshness=Freshness.CURRENT)
        except Exception as e:
            errors.append(f"FMP: {e}")
    return DataResult(None, "earnings calendar", error="; ".join(errors) or "No Finnhub/FMP key configured.")


def ipo_calendar(days: int = 30, force: bool = False) -> DataResult[pd.DataFrame]:
    cfg = load_config()
    if not cfg.finnhub_api_key:
        return DataResult(None, "Finnhub IPO calendar", error="FINNHUB_API_KEY not set.")
    start, end = date.today() - timedelta(days=7), date.today() + timedelta(days=days)

    def fetch():
        r = requests.get("https://finnhub.io/api/v1/calendar/ipo",
                         params={"from": start.isoformat(), "to": end.isoformat(), "token": cfg.finnhub_api_key},
                         timeout=30)
        r.raise_for_status()
        return r.json().get("ipoCalendar", [])
    try:
        raw = cache.cached(f"fh_ipo|{start}|{days}", 6 * 3600, fetch, force=force)
    except Exception as e:
        return DataResult(None, "Finnhub IPO calendar", error=str(e))
    df = pd.DataFrame([{"date": i.get("date"), "symbol": i.get("symbol"), "name": i.get("name"),
                        "exchange": i.get("exchange"), "status": i.get("status"), "price_range": i.get("price"),
                        "shares": i.get("numberOfShares"), "total_value_usd": i.get("totalSharesValue")}
                       for i in raw or []])
    return DataResult(df, "Finnhub IPO calendar", as_of=date.today(), freshness=Freshness.CURRENT,
                      notes="US IPOs (last 7 days + upcoming). Finnhub free tier.")


def combined_events(days: int = 14) -> tuple[pd.DataFrame, list[str]]:
    errs = []
    frames = []
    us = us_release_calendar(days)
    if us.ok and len(us.data):
        frames.append(us.data)
    elif us.error:
        errs.append(us.error)
    man = manual_events(days)
    if len(man):
        frames.append(man)
    df = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True) if frames else pd.DataFrame()
    return df, errs


def now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


# ============================================================================ Stage 2: richer calendar
import re as _re

FED_CAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                       "September", "October", "November", "December"], 1)}

# FRED release id → series that the release publishes: (series_id, label, transform, unit)
RELEASE_SERIES: dict[int, list[tuple[str, str, str, str]]] = {
    10: [("CPIAUCSL", "CPI YoY", "yoy", "%"), ("CPILFESL", "Core CPI YoY", "yoy", "%"), ("CPIAUCSL", "CPI MoM", "mom", "%")],
    46: [("PPIFIS", "PPI final demand MoM", "mom", "%"), ("PPIFIS", "PPI final demand YoY", "yoy", "%")],
    50: [("PAYEMS", "Nonfarm payrolls change", "diff", "k"), ("UNRATE", "Unemployment rate", "level", "%")],
    53: [("A191RL1Q225SBEA", "Real GDP q/q annualised", "level", "%")],
    54: [("PCEPILFE", "Core PCE YoY", "yoy", "%"), ("PCEPI", "PCE YoY", "yoy", "%")],
    9: [("RSAFS", "Retail sales MoM", "mom", "%")],
    192: [("JTSJOL", "JOLTS job openings", "level", "k")],
    180: [("ICSA", "Initial jobless claims", "level", "")],
    13: [("INDPRO", "Industrial production MoM", "mom", "%")],
}

EVENT_RELEVANCE: dict[str, str] = {
    "CPI": "Inflation surprises reprice Fed expectations → Treasury yields, the dollar, growth stocks and gold; "
           "higher US yields can pull money from EMs including India.",
    "PPI": "Pipeline inflation; matters most when it diverges from CPI or feeds PCE components.",
    "jobs": "Labour-market strength drives the Fed's reaction function; big surprises move yields, the dollar and "
            "rate-sensitive sectors.",
    "GDP": "Growth surprises shift recession odds, earnings expectations and cyclical vs defensive leadership.",
    "PCE": "The Fed's preferred inflation gauge; core PCE surprises directly shift rate expectations.",
    "retail": "Consumer demand (≈⅔ of US GDP); affects consumer discretionary and growth expectations.",
    "JOLTS": "Labour demand; falling openings point to a cooling labour market.",
    "claims": "Weekly, timely labour signal; sustained rises flag a weakening job market.",
    "industrial": "Manufacturing activity; relevant for industrials, materials and energy demand.",
    "FOMC": "The Fed's rate decision, statement and (*) projections/press conference — the single biggest scheduled "
            "driver of global yields, the dollar and risk appetite, with spillovers to the rupee and Indian equities.",
}


def relevance_for(event: str) -> str:
    e = event.lower()
    for k, v in (("cpi", "CPI"), ("ppi", "PPI"), ("jobs", "jobs"), ("gdp", "GDP"), ("pce", "PCE"), ("retail", "retail"),
                 ("jolts", "JOLTS"), ("claims", "claims"), ("industrial", "industrial"), ("fomc", "FOMC")):
        if k in e:
            return EVENT_RELEVANCE[v]
    return ""


def parse_fomc_html(html: str) -> list[dict]:
    """Extract scheduled FOMC meetings (year, month, days, SEP flag) from the Fed's calendar page."""
    out = []
    heads = list(_re.finditer(r"(\d{4}) FOMC Meetings", html))
    for i, h in enumerate(heads):
        year = int(h.group(1))
        seg = html[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        months = _re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>', seg)
        dates = _re.findall(r'fomc-meeting__date[^>]*>\s*([^<]+?)\s*<', seg)
        for mon, d in zip(months, dates):
            mon = mon.strip()
            last_mon = mon.split("/")[-1].strip()
            m = _re.match(r"(\d{1,2})(?:-(\d{1,2}))?(\*)?", d.strip())
            if not m or last_mon not in _MONTHS:
                continue
            end_day = int(m.group(2) or m.group(1))
            try:
                end = date(year, _MONTHS[last_mon], end_day)
            except ValueError:
                continue
            out.append({"decision_date": end, "label": f"{mon} {d.strip()}", "sep": bool(m.group(3)),
                        "notation_vote": "notation" in d.lower()})
    return sorted(out, key=lambda r: r["decision_date"])


def fomc_meetings(force: bool = False) -> DataResult[pd.DataFrame]:
    src = "Federal Reserve FOMC calendar (federalreserve.gov)"

    def fetch():
        r = requests.get(FED_CAL_URL, headers={"User-Agent": "Mozilla/5.0 (personal research tool)"}, timeout=30)
        r.raise_for_status()
        return r.text
    try:
        html = cache.cached("fed_fomc_cal", 24 * 3600, fetch, force=force)
        rows = parse_fomc_html(html or "")
    except Exception as e:
        return DataResult(None, src, error=f"FOMC calendar unavailable: {e}")
    if not rows:
        return DataResult(None, src, error="Could not parse FOMC meeting dates (page layout may have changed).")
    df = pd.DataFrame(rows)
    df["time_ist"] = [to_ist(d, time(14, 0)) for d in df["decision_date"]]
    return DataResult(df, src, as_of=date.today(), freshness=Freshness.CURRENT,
                      notes="Decision/statement at 14:00 ET on the last meeting day; * = Summary of Economic "
                            "Projections + press conference. " + FED_CAL_URL)


def _series_meta(sid: str, force: bool = False) -> dict:
    key = load_config().fred_api_key
    if not key:
        return {}

    def fetch():
        r = requests.get("https://api.stlouisfed.org/fred/series",
                         params={"series_id": sid, "api_key": key, "file_type": "json"}, timeout=20)
        r.raise_for_status()
        return (r.json().get("seriess") or [{}])[0]
    try:
        return cache.cached(f"fred_meta|{sid}", 6 * 3600, fetch, force=force) or {}
    except Exception:
        return {}


def release_readings(rid: int, event_date: date, force: bool = False, superseded: bool = False) -> list[dict]:
    """Latest & prior readings for the series a release publishes, and whether the latest came from this release.

    `superseded` = a later release of the same kind has already happened, so FRED's latest value is NOT this
    release's figure; we then refuse to label anything as this date's actual."""
    from tradingos.data.macro import MacroSeries, get_series
    if superseded:
        return [{"indicator": label, "status": "superseded by a later release — see FRED history",
                 "series": f"https://fred.stlouisfed.org/series/{sid}"} for sid, label, _, _ in RELEASE_SERIES.get(rid, [])]
    out = []
    for sid, label, transform, unit in RELEASE_SERIES.get(rid, []):
        res = get_series(MacroSeries(sid, label, "calendar", transform, unit), years=3, force=force)
        if not res.ok or len(res.data) < 2:
            out.append({"indicator": label, "error": res.error or "no data"})
            continue
        s = res.data
        meta = _series_meta(sid, force)
        upd = pd.Timestamp(meta["last_updated"]).date() if meta.get("last_updated") else None
        released = upd is not None and upd >= event_date and event_date <= date.today()
        latest, prior = float(s.iloc[-1]), float(s.iloc[-2])
        fmt = (lambda v: f"{v:,.0f}{unit}") if unit in ("k", "") and transform != "mom" else (lambda v: f"{v:.2f}{unit}")
        out.append({"indicator": label, "reference_period": s.index[-1].strftime("%b %Y" if transform != "level" or sid != "ICSA" else "%d %b %Y"),
                    "actual": fmt(latest) if released else None,
                    "previous": fmt(prior) if released else fmt(latest),
                    "previous_period": (s.index[-2] if released else s.index[-1]).strftime("%b %Y"),
                    "status": "released" if released else ("pending" if event_date >= date.today() else
                                                           "date passed — FRED not yet updated"),
                    "series": f"https://fred.stlouisfed.org/series/{sid}"})
    return out


def economic_calendar(past_days: int = 14, ahead_days: int = 45, force: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """US releases (FRED dates + readings), FOMC decisions (Fed site) and manual events (RBI/ECB/BoJ/BoE/China…)."""
    cfg = load_config()
    errors, rows = [], []
    start, end = date.today() - timedelta(days=past_days), date.today() + timedelta(days=ahead_days)
    if cfg.fred_api_key:
        def fetch():
            r = requests.get("https://api.stlouisfed.org/fred/releases/dates",
                             params={"api_key": cfg.fred_api_key, "file_type": "json", "realtime_start": start.isoformat(),
                                     "realtime_end": end.isoformat(), "include_release_dates_with_no_data": "true",
                                     "limit": 1000, "sort_order": "asc"}, timeout=30)
            r.raise_for_status()
            return r.json().get("release_dates", [])
        try:
            raw = cache.cached(f"fred_rel2|{start}|{end}", 6 * 3600, fetch, force=force) or []
            seen = set()
            for r in raw:
                rid = r.get("release_id")
                if rid not in US_RELEASES:
                    continue
                d = pd.Timestamp(r["date"]).date()
                if (rid, d) in seen:
                    continue
                seen.add((rid, d))
                label, imp, t = US_RELEASES[rid]
                rows.append({"date": d, "time_ist": to_ist(d, t) + (" (usual)" if t else ""), "country": "US",
                             "event": label, "importance": imp, "rid": rid,
                             "source": f"https://fred.stlouisfed.org/release?rid={rid}", "origin": "FRED schedule"})
        except Exception as e:
            errors.append(f"FRED release calendar: {e}")
    else:
        errors.append("FRED_API_KEY not set — US release calendar unavailable.")
    fomc = fomc_meetings(force)
    if fomc.ok:
        for _, m in fomc.data.iterrows():
            if start <= m["decision_date"] <= end:
                rows.append({"date": m["decision_date"], "time_ist": m["time_ist"], "country": "US",
                             "event": "FOMC rate decision" + (" + projections & press conference" if m["sep"] else ""),
                             "importance": "high", "rid": None, "source": FED_CAL_URL, "origin": "Federal Reserve"})
    else:
        errors.append(fomc.error)
    from tradingos.db.models import EconEvent
    from tradingos.db.session import session_scope
    with session_scope() as s:
        for r in s.scalars(select(EconEvent).where(EconEvent.event_date >= start, EconEvent.event_date <= end)).all():
            rows.append({"date": r.event_date, "time_ist": r.event_time or "", "country": r.country or "",
                         "event": r.title, "importance": r.importance, "rid": None,
                         "source": r.source_url or "manual entry (no source)", "origin": "manual", "id": r.id})
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["date", "importance"]).reset_index(drop=True)
        df["market_relevance"] = df["event"].map(relevance_for)
        today = date.today()
        last_past = df[df["rid"].notna() & (df["date"] <= today)].groupby("rid")["date"].max().to_dict()
        df["superseded"] = [bool(pd.notna(r) and d < last_past.get(r, d)) for r, d in zip(df["rid"], df["date"])]
    return df, errors


# ----------------------------------------------------------------------------- central banks
CENTRAL_BANKS = [
    {"bank": "Federal Reserve", "rate_series": "DFEDTARU", "rate_label": "Fed funds target (upper)",
     "sources": ["Federal Reserve — Monetary Policy", "Federal Reserve — All Press", "Federal Reserve — Speeches"],
     "official": "https://www.federalreserve.gov/monetarypolicy.htm"},
    {"bank": "European Central Bank", "rate_series": "ECBDFR", "rate_label": "Deposit facility rate",
     "sources": ["ECB — Press"], "official": "https://www.ecb.europa.eu/mopo/decisions/html/index.en.html"},
    {"bank": "Bank of Japan", "rate_series": "IRSTCI01JPM156N", "rate_label": "Call money rate (monthly, OECD via FRED)",
     "sources": ["Bank of Japan — What's New"], "official": "https://www.boj.or.jp/en/mopo/mpmdeci/index.htm"},
    {"bank": "Bank of England", "rate_series": None, "rate_label": "Bank Rate — no current FRED series",
     "sources": ["Bank of England — News"], "official": "https://www.bankofengland.co.uk/monetary-policy/the-interest-rate-bank-rate"},
    {"bank": "Reserve Bank of India", "rate_series": None, "rate_label": "Repo rate — no current FRED series",
     "sources": ["RBI — Press Releases"], "official": "https://www.rbi.org.in/Scripts/BS_ViewMonetaryPolicy.aspx"},
]


def central_bank_tracker(force: bool = False) -> list[dict]:
    from tradingos.data.macro import MacroSeries, get_series
    from tradingos.data.news import query_news
    from tradingos.intel.news_rank import ROUTINE_OFFICIAL
    from tradingos.data.news import kw_hit
    news = query_news(days=45, limit=2000)
    out = []
    for cb in CENTRAL_BANKS:
        item = {"bank": cb["bank"], "rate_label": cb["rate_label"], "official": cb["official"]}
        if cb["rate_series"]:
            r = get_series(MacroSeries(cb["rate_series"], cb["rate_label"], "cb", "level", "%"), years=3, force=force)
            if r.ok and len(r.data):
                s = r.data
                changes = s[s.diff().fillna(0) != 0]
                item.update({"rate": round(float(s.iloc[-1]), 2), "rate_as_of": str(s.index[-1].date()),
                             "last_change": (f"{changes.index[-1].date()} ({float(s.diff().loc[changes.index[-1]]):+.2f}pp)"
                                             if len(changes) else "no change in window"),
                             "rate_source": f"https://fred.stlouisfed.org/series/{cb['rate_series']}"})
            else:
                item["rate_error"] = r.error
        if len(news):
            sub = news[news["source"].isin(cb["sources"])].copy()
            sub["routine"] = [any(kw_hit(f" {h} ", k) for k in ROUTINE_OFFICIAL) and not kw_hit(h, "chair")
                              for h in sub["headline"]]
            sub = sub.sort_values(["routine", "published_utc"], ascending=[True, False])
            item["latest_communications"] = sub.head(6)[["published_utc", "headline", "url", "routine"]].to_dict("records")
        out.append(item)
    return out
