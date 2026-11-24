"""News & catalyst ingestion: RSS feeds, Yahoo ticker news, SEC EDGAR filings.

Every item keeps headline, source, publication timestamp and link. Classification
(category / sector / sentiment / information type) is a transparent keyword heuristic —
it is labelled as such in the UI. Gemini can add interpretation on top, never facts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import pandas as pd
import requests
from sqlalchemy import select

from tradingos.config import PROJECT_ROOT, load_config
from tradingos.data import cache
from tradingos.data.providers import get_market_provider, load_universe
from tradingos.db.models import NewsItem
from tradingos.db.session import session_scope

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AI-Trading-OS/0.1 personal research"}

# ----------------------------------------------------------------- classification rules
CATEGORY_RULES: dict[str, list[str]] = {
    "geopolitics": ["china", "tariff", "sanction", "export control", "war", "ukraine", "russia", "israel", "iran",
                    "taiwan", "opec", "middle east", "trade deal", "trade war", "beijing", "nato", "geopolit",
                    "conflict", "missile", "embargo", "supply chain"],
    "macro": ["fed ", "federal reserve", "fomc", "powell", "rate cut", "rate hike", "interest rate", "inflation",
              "cpi", "pce", "payroll", "jobs report", "unemployment", "gdp", "recession", "treasury yield",
              "bond yield", "consumer spending", "retail sales", "jobless", "economy", "economic"],
    "earnings": ["earnings", "quarterly results", "revenue", "guidance", "eps", "beats", "misses", "q1 ", "q2 ",
                 "q3 ", "q4 ", "outlook", "forecast"],
    "technology": ["ai ", "artificial intelligence", "chip", "semiconductor", "nvidia", "cloud", "data center",
                   "datacenter", "software", "openai", "gpu", "quantum"],
    "regulation": ["sec ", "antitrust", "ftc", "doj", "regulat", "lawsuit", "probe", "ban "],
    "commodities": ["gold", "silver", "bullion", "crude", "oil price", "brent", "wti", "opec", "copper",
                    "natural gas", "commodit", "metals"],
}
REGION_RULES: dict[str, list[str]] = {
    "India": ["india", "indian", "nifty", "sensex", "rbi", "sebi", "rupee", "modi", "nse ", "bse ", "mumbai",
              "delhi", "dalal street", "fii", "dii", "gst"],
    "Europe": ["ecb", "eurozone", "euro zone", "europe", "european", "germany", "france", "uk ", "britain",
               "bank of england", "lagarde", "dax", "ftse"],
    "Asia": ["china", "chinese", "japan", "boj", "bank of japan", "nikkei", "hong kong", "hang seng", "korea",
             "taiwan", "beijing", "tokyo", "asia"],
    "US": ["fed ", "federal reserve", "wall street", "s&p 500", "nasdaq", "dow ", "treasury", "u.s.",
           "american", "america", "white house", "congress", "powell", "trump", "washington"],
}
SECTOR_RULES: dict[str, list[str]] = {
    "Technology": ["chip", "semiconductor", "software", "cloud", "ai ", "gpu", "data center", "cyber"],
    "Energy": ["oil", "crude", "opec", "natural gas", "lng", "refin", "uranium"],
    "Financials": ["bank", "lender", "credit", "brokerage", "insurer", "fintech", "crypto", "bitcoin"],
    "Health Care": ["drug", "fda", "pharma", "biotech", "vaccine", "obesity", "glp-1", "medicare"],
    "Industrials": ["defense", "aerospace", "airline", "railroad", "boeing", "manufactur", "infrastructure"],
    "Consumer Discretionary": ["retail", "consumer", "automaker", "ev ", "electric vehicle", "travel", "housing"],
    "Utilities": ["utility", "power grid", "electricity", "nuclear power"],
    "Materials": ["copper", "steel", "lithium", "rare earth", "gold", "mining"],
    "Real Estate": ["reit", "commercial real estate", "mortgage"],
    "Communication Services": ["streaming", "social media", "telecom", "advertis"],
}
GEO_IMPACT_MAP: dict[str, str] = {
    "tariff": "Tariffs → watch importers/retail (XLY), industrials, semis supply chains; possible input-cost pressure.",
    "export control": "Chip export controls → semis with China revenue exposure (NVDA, AMD, AMAT, LRCX, KLAC, ASML).",
    "china": "US–China developments → semis, Apple supply chain, industrial exporters, rare earths (MP).",
    "taiwan": "Taiwan risk → TSM and the semiconductor supply chain (SMH).",
    "opec": "OPEC decisions → oil producers (XLE), airlines, inflation expectations.",
    "oil": "Oil-price moves → energy (XLE), airlines/transport costs, inflation expectations.",
    "sanction": "Sanctions → energy/commodity supply, defense, affected multinationals.",
    "war": "Conflict risk → defense (ITA, LMT, NOC, RTX), energy, safe havens (GLD, TLT); risk-off for equities.",
    "rare earth": "Rare-earth supply → MP Materials, EV and defense supply chains.",
}
POS = ["beat", "beats", "surge", "soar", "jump", "rally", "record", "upgrade", "raises", "strong", "gain",
       "rises", "rise", "boost", "approval", "wins", "tops", "accelerat", "outperform", "bullish", "rebound"]
NEG = ["miss", "misses", "plunge", "slump", "fall", "falls", "drop", "cut", "downgrade", "weak", "lawsuit",
       "probe", "recall", "warn", "loss", "decline", "tumble", "sink", "slide", "bearish", "layoff", "ban",
       "tariff", "sanction", "recession", "fear", "selloff", "sell-off", "rout"]
SPECULATION = ["could", "may ", "might", "reportedly", "rumor", "rumour", "considering", "weighs", "in talks",
               "sources say", "people familiar", "speculat", "would"]
INTERPRETATION = ["analyst", "says", "expects", "forecast", "upgrade", "downgrade", "price target", "why ",
                  "what ", "should", "opinion", "strategist", "view", "outlook", "how to", "?"]


_KW_CACHE: dict[str, re.Pattern] = {}


def kw_hit(text: str, kw: str) -> bool:
    """Keyword match on word boundaries. Short keywords (≤4 chars, e.g. "war", "ai", "ban", "fed") must match a
    whole word; longer ones may be word prefixes so stems like "regulat" or "semiconductor" still work.
    Avoids substring false positives such as "Warsh" → "war" or "bank" → "ban"."""
    k = kw.strip().lower()
    pat = _KW_CACHE.get(k)
    if pat is None:
        esc = re.escape(k)
        pat = re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])" if len(k) <= 4 else rf"(?<![a-z0-9]){esc}")
        _KW_CACHE[k] = pat
    return bool(pat.search(text.lower()))


def kw_count(text: str, kws) -> int:
    return sum(kw_hit(text, k) for k in kws)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", "", text.lower())).strip()


def dedupe_key(headline: str) -> str:
    return hashlib.sha1(_norm(headline)[:90].encode()).hexdigest()[:32]


def classify_category(text: str, default: str = "markets") -> str:
    t = f" {text.lower()} "
    scores = {c: kw_count(t, kws) for c, kws in CATEGORY_RULES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default


def classify_sector(text: str) -> str:
    t = f" {text.lower()} "
    scores = {s: kw_count(t, kws) for s, kws in SECTOR_RULES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


def classify_sentiment(text: str) -> str:
    t = f" {text.lower()} "
    p = kw_count(t, POS)
    n = kw_count(t, NEG)
    return "positive" if p > n else "negative" if n > p else "neutral"


def classify_info_type(text: str, official: bool) -> str:
    if official:
        return "Confirmed (official source)"
    t = f" {text.lower()} "
    if any(kw_hit(t, k) for k in SPECULATION):
        return "Speculation / unconfirmed"
    if "?" in t or any(kw_hit(t, k) for k in INTERPRETATION if k != "?"):
        return "Analyst interpretation / opinion"
    return "Reported (news media)"


def classify_region(text: str, hint: str = "", official: bool = False) -> str:
    """Region the story is ABOUT. Official feeds keep their region (an RBI release is India). Otherwise the
    strongest keyword region wins — so an Indian outlet's Wall Street story is tagged US — then the feed's
    region, then Global."""
    if official and hint:
        return hint
    scores = {r: kw_count(text, kws) for r, kws in REGION_RULES.items()}
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        if hint and scores.get(hint, 0) == scores[best]:
            return hint
        return best
    return hint or "Global"


def geo_impact(text: str) -> str:
    t = text.lower()
    hits = [v for k, v in GEO_IMPACT_MAP.items() if kw_hit(t, k)]
    return " ".join(dict.fromkeys(hits))


AMBIGUOUS_NAMES = {"Target", "Visa", "Block", "Ford"}  # common words → too many false matches
_TICKER_CACHE: list[tuple[str, re.Pattern]] | None = None


def _ticker_patterns() -> list[tuple[str, re.Pattern]]:
    global _TICKER_CACHE
    if _TICKER_CACHE is None:
        uni = load_universe()
        pats = []
        for _, r in uni[uni["type"] == "Stock"].iterrows():
            name = re.sub(r"\b(inc|corp|corporation|holdings|company|technologies|group|plc)\b\.?", "",
                          r["name"], flags=re.I).strip()
            if len(name) >= 4 and name not in AMBIGUOUS_NAMES:
                pats.append((r["ticker"], re.compile(rf"\b{re.escape(name)}\b")))
        _TICKER_CACHE = pats
    return _TICKER_CACHE


def extract_tickers(text: str) -> list[str]:
    found = [t for t, p in _ticker_patterns() if p.search(text)]
    found += re.findall(r"\$([A-Z]{1,5})\b", text)
    return list(dict.fromkeys(found))


def _parse_time(entry) -> datetime | None:
    for key in ("published", "updated"):
        val = entry.get(key)
        if val:
            try:
                dt = parsedate_to_datetime(val)
            except Exception:
                try:
                    dt = pd.Timestamp(val).to_pydatetime()
                except Exception:
                    continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return None


def enrich(item: dict, official: bool = False, category_hint: str = "markets", region_hint: str = "") -> dict:
    text = f"{item['headline']} {item.get('summary', '')}"
    cat = classify_category(text, default=category_hint)
    item["region"] = classify_region(text, region_hint, official)
    item.setdefault("tickers", extract_tickers(text))
    item["category"] = cat
    item["sector"] = classify_sector(text)
    item["sentiment"] = classify_sentiment(item["headline"])
    item["info_type"] = classify_info_type(item["headline"], official)
    item["impact"] = geo_impact(text) if cat in ("geopolitics", "macro", "commodities") else ""
    return item


# ----------------------------------------------------------------- fetchers
def load_feed_config() -> list[dict]:
    with open(PROJECT_ROOT / "config" / "news_feeds.json") as f:
        return json.load(f)["feeds"]


def fetch_rss(feed: dict) -> list[dict]:
    def go():
        r = requests.get(feed["url"], headers=UA, timeout=20)
        r.raise_for_status()
        return r.content

    content = cache.cached(f"rss|{feed['url']}", 20 * 60, go)
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        summary = re.sub(r"<[^>]+>", "", e.get("summary", "") or "").strip()[:600]
        out.append(enrich({"headline": title, "summary": summary, "source": feed["name"],
                           "url": e.get("link", ""), "published_at": _parse_time(e)},
                          official=feed.get("official", False), category_hint=feed.get("category", "markets"),
                          region_hint=feed.get("region", "")))
    return out


def fetch_finnhub_general(category: str = "general") -> list[dict]:
    """Finnhub market news (free tier: general / forex / merger). Headlines + short summaries + links only."""
    key = load_config().finnhub_api_key
    if not key:
        return []

    def go():
        r = requests.get("https://finnhub.io/api/v1/news", params={"category": category, "token": key}, timeout=20)
        r.raise_for_status()
        return r.json()

    raw = cache.cached(f"fh_news|{category}", 20 * 60, go) or []
    out = []
    for n in raw:
        title = (n.get("headline") or "").strip()
        if not title or not n.get("datetime"):
            continue
        out.append(enrich({"headline": title, "summary": (n.get("summary") or "")[:600],
                           "source": f"{n.get('source') or 'Finnhub'} (via Finnhub)", "url": n.get("url", ""),
                           "published_at": datetime.fromtimestamp(n["datetime"], tz=timezone.utc).replace(tzinfo=None)},
                          official=False, category_hint="markets" if category == "general" else "macro"))
    return out


def fetch_edgar(ticker: str, forms: tuple[str, ...] = ("8-K", "10-Q", "10-K")) -> tuple[list[dict], str | None]:
    """Recent SEC filings for a ticker. Requires SEC_USER_AGENT (SEC fair-access policy)."""
    ua = load_config().sec_user_agent
    if not ua:
        return [], "SEC EDGAR disabled: set SEC_USER_AGENT in .env (SEC requires a contact User-Agent)."
    items = []
    for form in forms:
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               f"&CIK={ticker}&type={form}&dateb=&owner=include&count=5&output=atom")
        try:
            content = cache.cached(f"edgar|{ticker}|{form}", 3600,
                                   lambda u=url: requests.get(u, headers={"User-Agent": ua}, timeout=20).content)
            for e in feedparser.parse(content).entries:
                items.append(enrich({"headline": f"{ticker}: {e.get('title', form)}",
                                     "summary": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:400],
                                     "source": "SEC EDGAR", "url": e.get("link", ""),
                                     "published_at": _parse_time(e), "tickers": [ticker]},
                                    official=True, category_hint="earnings" if form != "8-K" else "company"))
        except Exception as ex:
            return items, f"EDGAR {form} failed: {ex}"
    return items, None


def refresh_news(tickers: list[str] | None = None, max_age_days: int = 7) -> dict:
    """Fetch all feeds (+ ticker news), dedupe, drop stale, persist. Returns a status report."""
    status = {"fetched": 0, "stored": 0, "duplicates": 0, "stale": 0, "errors": []}
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max_age_days)
    items: list[dict] = []
    for feed in load_feed_config():
        try:
            items += fetch_rss(feed)
        except Exception as e:
            status["errors"].append(f"{feed['name']}: {e}")
    for fcat in ("general", "forex"):
        try:
            items += fetch_finnhub_general(fcat)
        except Exception as e:
            status["errors"].append(f"Finnhub {fcat} news: {e}")
    prov = get_market_provider()
    for t in tickers or []:
        res = prov.news(t)
        if res.ok:
            items += [enrich(i, official=False, category_hint="company") for i in res.data]
        elif res.error:
            status["errors"].append(f"{t} news: {res.error}")
        edgar, err = fetch_edgar(t)
        items += edgar
        if err and err not in status["errors"]:
            status["errors"].append(err)
    status["fetched"] = len(items)

    with session_scope() as s:
        existing = set(s.scalars(select(NewsItem.dedupe_key)).all())
        for it in items:
            if not it.get("published_at") or it["published_at"] < cutoff:
                status["stale"] += 1
                continue
            key = dedupe_key(it["headline"])
            if key in existing:
                status["duplicates"] += 1
                continue
            existing.add(key)
            s.add(NewsItem(dedupe_key=key, headline=it["headline"][:500], summary=it.get("summary", ""),
                           source=it["source"], url=it.get("url", ""), published_at=it["published_at"],
                           tickers=",".join(it.get("tickers") or []), category=it.get("category", ""),
                           sector=it.get("sector", ""), sentiment=it.get("sentiment", ""),
                           impact=it.get("impact", ""), info_type=it.get("info_type", ""),
                           region=it.get("region", "")))
            status["stored"] += 1
    return status


def query_news(days: int = 7, category: str | None = None, ticker: str | None = None,
               sector: str | None = None, limit: int = 300, region: str | None = None) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with session_scope() as s:
        q = select(NewsItem).where(NewsItem.published_at >= cutoff)
        if category:
            q = q.where(NewsItem.category == category)
        if sector:
            q = q.where(NewsItem.sector == sector)
        if region:
            q = q.where(NewsItem.region == region)
        if ticker:
            q = q.where(NewsItem.tickers.like(f"%{ticker.upper()}%"))
        rows = s.scalars(q.order_by(NewsItem.published_at.desc()).limit(limit)).all()
        data = [{"published_utc": r.published_at, "headline": r.headline, "source": r.source, "url": r.url,
                 "tickers": r.tickers, "category": r.category, "sector": r.sector, "sentiment": r.sentiment,
                 "info_type": r.info_type, "impact": r.impact, "summary": r.summary,
                 "region": r.region or classify_region(f"{r.headline} {r.summary}"),
                 "retrieved_utc": r.retrieved_at} for r in rows]
    if ticker:  # exact token match (LIKE can over-match e.g. "T" in "TSLA")
        data = [d for d in data if ticker.upper() in d["tickers"].split(",")]
    return pd.DataFrame(data)


def reclassify_stored(days: int = 30) -> int:
    """Re-run the (deterministic) classifiers over stored items — use after changing keyword rules."""
    feeds = {f["name"]: f for f in load_feed_config()}
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    n = 0
    with session_scope() as s:
        for r in s.scalars(select(NewsItem).where(NewsItem.published_at >= cutoff)).all():
            f = feeds.get(r.source, {})
            official = bool(f.get("official")) or r.source == "SEC EDGAR"
            item = enrich({"headline": r.headline, "summary": r.summary or "", "tickers": (r.tickers or "").split(",")},
                          official=official, category_hint=f.get("category", r.category or "markets"),
                          region_hint=f.get("region", ""))
            r.category, r.sector, r.sentiment = item["category"], item["sector"], item["sentiment"]
            r.info_type, r.impact, r.region = item["info_type"], item["impact"], item["region"]
            n += 1
    return n
