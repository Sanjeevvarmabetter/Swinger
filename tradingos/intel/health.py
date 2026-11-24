"""Provider health & plan-permission checks.

Each check calls one real endpoint with a tiny request and classifies the outcome:
  OK · NOT IN PLAN (401/402/403) · NOT CONFIGURED (no key) · ERROR (network/other).
API keys are never logged or returned — responses are reduced to a short status message.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
from sqlalchemy import func, select

from tradingos.config import load_config
from tradingos.data import cache


@dataclass
class Check:
    provider: str
    capability: str
    status: str
    detail: str
    used_for: str
    latency_ms: int | None = None


def _probe(provider: str, capability: str, used_for: str, url: str, params: dict, key_present: bool,
           ok_fn=lambda j: True, secret: str = "") -> Check:
    if not key_present:
        return Check(provider, capability, "NOT CONFIGURED", "API key not set in .env", used_for)
    t0 = time.time()
    try:
        r = requests.get(url, params=params, timeout=15)
        ms = int((time.time() - t0) * 1000)
        if r.status_code in (401, 402, 403):
            return Check(provider, capability, "NOT IN PLAN", f"HTTP {r.status_code} — endpoint not available on this "
                                                               "subscription/key", used_for, ms)
        if r.status_code == 429:
            return Check(provider, capability, "RATE LIMITED", "HTTP 429", used_for, ms)
        r.raise_for_status()
        j = r.json()
        good = ok_fn(j)
        return Check(provider, capability, "OK" if good else "EMPTY", "responded" if good else "responded with no data",
                     used_for, ms)
    except Exception as e:
        msg = str(e).replace(secret, "***") if secret else str(e)
        return Check(provider, capability, "ERROR", msg[:120], used_for)


def run_checks(force: bool = False) -> list[dict]:
    def go():
        cfg = load_config()
        today = date.today()
        fh, fm, fr = cfg.finnhub_api_key, cfg.fmp_api_key, cfg.fred_api_key
        checks = [
            _probe("FRED", "Series observations", "Macro dashboard, real yields, credit spreads",
                   "https://api.stlouisfed.org/fred/series/observations",
                   {"series_id": "DGS10", "api_key": fr, "file_type": "json", "limit": 1, "sort_order": "desc"},
                   bool(fr), lambda j: bool(j.get("observations")), fr),
            _probe("FRED", "Release calendar", "US economic release dates",
                   "https://api.stlouisfed.org/fred/releases/dates",
                   {"api_key": fr, "file_type": "json", "limit": 5}, bool(fr), lambda j: "release_dates" in j, fr),
            _probe("Finnhub", "Quote", "Settings connectivity test", "https://finnhub.io/api/v1/quote",
                   {"symbol": "AAPL", "token": fh}, bool(fh), lambda j: bool(j.get("c")), fh),
            _probe("Finnhub", "General market news", "News engine (general + forex categories)",
                   "https://finnhub.io/api/v1/news", {"category": "general", "token": fh}, bool(fh),
                   lambda j: isinstance(j, list) and len(j) > 0, fh),
            _probe("Finnhub", "Company news", "Ticker news", "https://finnhub.io/api/v1/company-news",
                   {"symbol": "AAPL", "from": (today - timedelta(days=3)).isoformat(), "to": today.isoformat(),
                    "token": fh}, bool(fh), lambda j: isinstance(j, list), fh),
            _probe("Finnhub", "Earnings calendar", "Earnings calendar", "https://finnhub.io/api/v1/calendar/earnings",
                   {"from": today.isoformat(), "to": (today + timedelta(days=3)).isoformat(), "token": fh}, bool(fh),
                   lambda j: "earningsCalendar" in j, fh),
            _probe("Finnhub", "IPO calendar", "IPO calendar", "https://finnhub.io/api/v1/calendar/ipo",
                   {"from": today.isoformat(), "to": (today + timedelta(days=30)).isoformat(), "token": fh}, bool(fh),
                   lambda j: "ipoCalendar" in j, fh),
            _probe("Finnhub", "Economic calendar", "Would supply forecasts/actuals for macro releases",
                   "https://finnhub.io/api/v1/calendar/economic", {"token": fh}, bool(fh),
                   lambda j: "economicCalendar" in j, fh),
            _probe("FMP", "Quote", "Settings connectivity test", "https://financialmodelingprep.com/stable/quote",
                   {"symbol": "AAPL", "apikey": fm}, bool(fm), lambda j: isinstance(j, list) and len(j) > 0, fm),
            _probe("FMP", "Earnings calendar", "Earnings calendar fallback",
                   "https://financialmodelingprep.com/stable/earnings-calendar",
                   {"from": today.isoformat(), "to": (today + timedelta(days=3)).isoformat(), "apikey": fm}, bool(fm),
                   lambda j: isinstance(j, list), fm),
            _probe("FMP", "Treasury rates", "Available, not yet used (FRED preferred)",
                   "https://financialmodelingprep.com/stable/treasury-rates", {"apikey": fm}, bool(fm),
                   lambda j: isinstance(j, list) and len(j) > 0, fm),
            _probe("FMP", "Economic calendar", "Would supply forecasts/actuals for macro releases",
                   "https://financialmodelingprep.com/stable/economic-calendar", {"apikey": fm}, bool(fm),
                   lambda j: isinstance(j, list), fm),
            _probe("FMP", "General news", "Would add a news source",
                   "https://financialmodelingprep.com/stable/news/general-latest", {"limit": 1, "apikey": fm}, bool(fm),
                   lambda j: isinstance(j, list), fm),
            _probe("CFTC", "Commitments of Traders (Socrata)", "Gold/silver/copper/oil positioning",
                   "https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
                   {"$limit": 1, "$where": "cftc_contract_market_code='088691'"}, True,
                   lambda j: isinstance(j, list) and len(j) > 0),
        ]
        checks.append(Check("Gemini", "Generate", "OK" if cfg.gemini_configured else "NOT CONFIGURED",
                            f"model {cfg.gemini_model} (use Settings → Test Gemini for a live call)"
                            if cfg.gemini_configured else "GEMINI_API_KEY not set", "Briefing editor & AI analysts"))
        checks.append(Check("SEC EDGAR", "Filings (Atom)", "OK" if cfg.sec_user_agent else "NOT CONFIGURED",
                            "User-Agent configured" if cfg.sec_user_agent else
                            "Set SEC_USER_AGENT in .env (SEC fair-access policy requires contact info)",
                            "Company filings in ticker news"))
        checks.append(Check("Groq", "Chat completions", "OK" if cfg.groq_configured else "NOT CONFIGURED",
                            f"model {cfg.groq_model} (use Settings → Test connection for a live call)"
                            if cfg.groq_configured else "GROQ_API_KEY not set", "AI Research Chat & briefings"))
        from tradingos.intel import xintel
        checks.append(Check("X (Twitter) API", "Recent search", "OK" if xintel.configured() else "NOT CONFIGURED",
                            f"bearer token set · budget {xintel.daily_limit()} requests/day" if xintel.configured()
                            else "Set X_BEARER_TOKEN in .env (paid X API plan or credits required)",
                            "X Intelligence"))
        return [asdict(c) for c in checks]
    return cache.cached("health|checks", 3600, go, force=force)


def feed_status() -> pd.DataFrame:
    """Per news source: items stored, newest published time, newest retrieval — from the local DB."""
    from tradingos.data.news import load_feed_config
    from tradingos.db.models import NewsItem
    from tradingos.db.session import session_scope
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_scope() as s:
        rows = s.execute(select(NewsItem.source, func.count(NewsItem.id), func.max(NewsItem.published_at),
                                func.max(NewsItem.retrieved_at)).group_by(NewsItem.source)).all()
    have = {r[0]: r for r in rows}
    out = []
    for f in load_feed_config():
        r = have.get(f["name"])
        newest = r[2] if r else None
        age_h = round((now - newest).total_seconds() / 3600, 1) if newest else None
        out.append({"Feed": f["name"], "Region": f.get("region", ""), "Official": f.get("official", False),
                    "Items stored": r[1] if r else 0, "Newest item (UTC)": newest, "Age (h)": age_h,
                    "Last retrieved (UTC)": r[3] if r else None,
                    "Status": "No items yet" if not r else ("Quiet >72h" if age_h and age_h > 72 else "Active"),
                    "URL": f["url"]})
    other = [r for k, r in have.items() if k not in {f["name"] for f in load_feed_config()}]
    fin = [r for r in other if "Finnhub" in r[0]]
    if fin:
        out.append({"Feed": "Finnhub-sourced outlets (aggregated)", "Region": "", "Official": False,
                    "Items stored": sum(r[1] for r in fin), "Newest item (UTC)": max(r[2] for r in fin if r[2]),
                    "Age (h)": None, "Last retrieved (UTC)": max(r[3] for r in fin), "Status": "Active", "URL": ""})
    return pd.DataFrame(out)
