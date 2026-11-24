"""AI Research Chat context: choose the slice of today's data that is relevant to a question.

Python decides what the model sees. Every news item handed to the model carries its URL, and the same list is
returned as `sources` so the UI can render a verified, clickable source list and strip any link the model invents.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

INTENTS: dict[str, tuple[str, ...]] = {
    "us": ("us market", "us stock", "s&p", "spx", "nasdaq", "dow", "wall street", "russell", "american", "u.s.",
           "us equit", "fed ", "federal reserve", "treasury"),
    "india": ("india", "indian", "nifty", "sensex", "rbi", "sebi", "rupee", "inr", "nse", "bse", "dalal"),
    "gold": ("gold", "silver", "bullion", "precious", "commodit", "crude", "oil", "brent", "wti", "copper", "metal",
             "natural gas"),
    "geo": ("geopolit", "war", "sanction", "tariff", "china", "russia", "ukraine", "israel", "iran", "gaza", "taiwan",
            "middle east", "conflict", "election", "nato", "trade deal", "red sea", "opec"),
    "tech": ("ai ", " ai", "artificial intelligence", "semiconductor", "chip", "nvidia", "tsmc", "data center",
             "datacenter", "hyperscaler", "tech", "software", "cloud", "gpu"),
    "macro": ("inflation", "cpi", "pce", "rate cut", "rate hike", "interest rate", "yield", "bond", "central bank",
              "ecb", "boj", "gdp", "jobs", "payroll", "unemployment", "recession", "dollar", "dxy", "fx", "currency",
              "fomc", "economy", "economic"),
    "global": ("global", "world", "europe", "asia", "japan", "nikkei", "hang seng", "dax", "ftse", "emerging",
               "cross-asset", "risk-on", "risk-off", "risk appetite"),
}
INTENT_MARKETS = {
    "us": ("us_indices", "volatility", "us_sectors_by_1w", "us_themes_by_1w", "magnificent_7", "us_yields"),
    "india": ("india", "india_sectors_by_1w", "currencies"),
    "gold": ("precious_metals", "energy_industrial", "currencies", "us_yields"),
    "geo": ("energy_industrial", "precious_metals", "volatility", "currencies"),
    "tech": ("us_themes_by_1w", "magnificent_7", "us_sectors_by_1w"),
    "macro": ("us_yields", "credit_bonds", "currencies", "volatility"),
    "global": ("us_indices", "europe", "asia_pacific", "india", "currencies", "volatility"),
}
INTENT_NEWS = {
    "us": {"region": {"US"}, "category": {"markets", "earnings", "macro"}},
    "india": {"region": {"India"}, "category": set()},
    "gold": {"region": set(), "category": {"commodities"}},
    "geo": {"region": set(), "category": {"geopolitics"}},
    "tech": {"region": set(), "category": {"technology"}},
    "macro": {"region": set(), "category": {"macro"}},
    "global": {"region": {"Global", "Europe", "Asia"}, "category": set()},
}
STOP = set("""a an the and or of to in on for is are was were be by with what why how when which who whom whose does
do did it its this that these those about from at as into over under than then today now latest recent current
me my i you your our we us please tell give explain show analysis analyse analyze detailed brief summary market
markets moving move price prices performance happening going""".split())
_GENERIC_NAME = {"spdr", "ishares", "invesco", "vaneck", "global", "first", "select", "sector", "the", "united",
                 "american", "general", "international", "vanguard", "direxion", "proshares", "wisdomtree"}


def detect_intents(question: str) -> list[str]:
    q = f" {question.lower()} "
    return [k for k, kws in INTENTS.items() if any(kw in q for kw in kws)]


def _name_map() -> dict[str, str]:
    from tradingos.intel.instruments import GEO_SENSITIVE, MAG7
    m = {k.lower(): v for k, v in MAG7.items()}
    m.update({"google": "GOOGL", "facebook": "META", "tsmc": "TSM", "taiwan semiconductor": "TSM"})
    m.update({k.lower().split(" (")[0]: v for k, v in GEO_SENSITIVE.items()})
    try:
        from tradingos.data.providers import load_universe
        for _, r in load_universe().iterrows():
            if r.get("type") == "ETF":
                continue
            first = re.split(r"[\s,.]+", str(r["name"]).lower())[0]
            if len(first) > 3 and first not in _GENERIC_NAME:
                m.setdefault(first, r["ticker"])
    except Exception:
        pass
    return m


def extract_tickers(question: str, max_n: int = 2) -> list[str]:
    """Tickers named in a question: $NVDA, a known symbol in capitals, or a known company name."""
    found: list[str] = re.findall(r"\$([A-Za-z]{1,5}(?:\.[A-Z]{1,2})?)\b", question)
    known: set[str] = set()
    try:
        from tradingos.data.providers import load_universe
        from tradingos.intel.instruments import GEO_SENSITIVE, MAG7
        known = set(load_universe()["ticker"]) | set(MAG7.values()) | set(GEO_SENSITIVE.values())
    except Exception:
        pass
    for w in re.findall(r"\b[A-Z]{2,5}\b", question):
        if w in known and w not in {"AI", "US", "UK", "EU", "GDP", "CPI", "FED", "RBI", "ETF", "IPO", "CEO", "USD", "INR"}:
            found.append(w)
    ql = question.lower()
    for name, t in _name_map().items():
        if re.search(rf"\b{re.escape(name)}\b", ql):
            found.append(t)
    return list(dict.fromkeys(t.upper() for t in found))[:max_n]


def _terms(question: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9&\-]{2,}", question.lower()) if w not in STOP}


def _news_relevance(item: dict, terms: set[str], intents: list[str], tickers: list[str]) -> float:
    text = f"{item.get('headline', '')} {item.get('summary', '')} {item.get('topics', '')}".lower()
    s = sum(2.0 for t in terms if t in text)
    for k in intents:
        rule = INTENT_NEWS[k]
        if item.get("region") in rule["region"] or item.get("category") in rule["category"]:
            s += 1.5
    s += 3.0 * sum(1 for t in tickers if re.search(rf"\b{t.lower()}\b", text))
    s += {"MUST KNOW": 1.5, "IMPORTANT": 0.8, "INTERESTING": 0.3}.get(item.get("tier", ""), 0)
    return s


def company_brief(ctx: dict) -> dict:
    """Compact, model-friendly company snapshot from services.stock_context()."""
    if "error" in ctx:
        return {"ticker": ctx.get("ticker"), "error": ctx["error"]}
    d = ctx.get("daily", {}) or {}
    keep = ("as_of", "close", "change_1d_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "sma50", "sma200",
            "above_sma200", "rsi14", "high_52w", "low_52w", "pct_from_52w_high", "rs_vs_spy_pp", "trend")
    f = ctx.get("fundamentals", {}) or {}
    return {
        "ticker": ctx["ticker"], "name": ctx.get("name"), "sector": ctx.get("sector"),
        "price_data_source": (ctx.get("data_meta") or {}).get("source"),
        "price_freshness": (ctx.get("data_meta") or {}).get("freshness"),
        "price_snapshot_daily": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items() if k in keep},
        "fundamentals": f.get("info", {}), "recent_quarters": f.get("quarters", [])[-4:],
        "next_earnings": str(f.get("next_earnings")) if f.get("next_earnings") else None,
        "news": [{"headline": n.get("headline"), "source": n.get("source"), "url": n.get("url"),
                  "published_utc": str(n.get("published_utc"))[:16]} for n in ctx.get("news", [])[:8]],
    }


def select_context(payload: dict, question: str, companies: list[dict] | None = None,
                   max_news: int = 14) -> tuple[dict, list[dict]]:
    """Build the chat CONTEXT from a briefing payload. Returns (context, sources)."""
    intents = detect_intents(question)
    tickers = [c.get("ticker") for c in companies or [] if c.get("ticker")]
    markets = payload.get("markets", {})
    keys: list[str] = []
    for k in (intents or ["global"]):
        keys += INTENT_MARKETS.get(k, ())
    if not intents:
        keys += ["us_indices", "india", "precious_metals", "energy_industrial", "us_yields"]
    keys = list(dict.fromkeys(keys))
    ctx: dict = {
        "question_received_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "data_generated": payload.get("edition", {}).get("generated_at_utc"),
        "detected_topics": intents or ["general"],
        "data_notes": ("Market data are daily bars from free delayed sources (not real-time). 'Freshness' says how "
                       "current each row is. News = headlines + short feed summaries, ranked by deterministic rules."),
        "risk_appetite_checklist": payload.get("risk_appetite"),
        "markets": {k: markets[k] for k in keys if markets.get(k)},
    }
    if "gold" in intents and payload.get("gold"):
        g = dict(payload["gold"])
        g.pop("drivers_1y", None)
        # Make the measurement window explicit so a 1-month change is never reported as a daily move.
        g["drivers_1m"] = [{("Change over last 1 month" if k == "Change" else k): v for k, v in r.items()}
                           for r in g.get("drivers_1m", []) or []]
        ctx["gold_drivers"] = g
    if ("geo" in intents or "gold" in intents) and payload.get("geopolitics"):
        ctx["geopolitics_theaters"] = [
            {**{k: t.get(k) for k in ("theater", "stories_7d", "trend", "attention_ratio")},
             "top_events": [{k: e.get(k) for k in ("headline", "source", "url", "when_utc", "tier")}
                            for e in t.get("top_events", [])],
             **({"transmission_framework": t["transmission_framework"]}
                if "geo" in intents and t.get("transmission_framework") else {})}
            for t in payload["geopolitics"]][: 6 if "geo" in intents else 2]
    if "tech" in intents and payload.get("trends_radar"):
        ctx["trends_radar"] = [{k: v for k, v in r.items() if k != "Evidence"} for r in payload["trends_radar"]]
    if "macro" in intents or "us" in intents or "india" in intents:
        ctx["economic_calendar"] = [e for e in payload.get("economic_calendar", []) if e.get("importance") != "low"][:20]
        if payload.get("central_banks"):
            ctx["central_banks"] = payload["central_banks"]
    if payload.get("upcoming_events"):
        ctx["upcoming_events"] = payload["upcoming_events"][:15]

    terms = _terms(question)
    news = sorted(payload.get("news_ranked", []), key=lambda n: _news_relevance(n, terms, intents, tickers),
                  reverse=True)
    chosen = [n for n in news if n.get("tier") != "IGNORE FOR NOW"][:max_news]
    sources: list[dict] = []
    ctx_news = []
    for i, n in enumerate(chosen, 1):
        ctx_news.append({"id": f"N{i}", "headline": n["headline"], "source": n["source"], "url": n["url"],
                         "published_utc": n.get("published_utc"), "tier": n.get("tier"),
                         "info_type": n.get("info_type"), "region": n.get("region"),
                         "summary": (n.get("summary") or "")[:220],
                         "also_reported_by": n.get("also_reported_by") or None})
        sources.append({"id": f"N{i}", "title": n["headline"], "source": n["source"], "url": n["url"],
                        "published": f"{n.get('published_utc')} UTC" if n.get("published_utc") else ""})
    ctx["news"] = ctx_news

    if companies:
        import copy
        companies = copy.deepcopy(companies)
        k = 0
        for c in companies:
            for n in c.get("news", []):
                if n.get("url"):
                    k += 1
                    n["id"] = f"C{k}"
                    sources.append({"id": f"C{k}", "title": n["headline"], "source": n["source"], "url": n["url"],
                                    "published": f"{n.get('published_utc')} UTC" if n.get("published_utc") else ""})
        ctx["companies"] = companies
    # Official calendar / central-bank links are legitimate citation targets too.
    import copy
    if ctx.get("central_banks"):
        ctx["central_banks"] = copy.deepcopy(ctx["central_banks"])
    if ctx.get("geopolitics_theaters"):
        ctx["geopolitics_theaters"] = copy.deepcopy(ctx["geopolitics_theaters"])
    k = 0
    for cb in ctx.get("central_banks", []) or []:
        for c in cb.get("latest_communications", []):
            if c.get("url"):
                k += 1
                c["id"] = f"B{k}"
                sources.append({"id": f"B{k}", "title": c["headline"], "source": cb.get("bank", "Central bank"),
                                "url": c["url"], "published": f"{c.get('published_utc')} UTC"})
    k = 0
    for t in ctx.get("geopolitics_theaters", []) or []:
        for e in t.get("top_events", []):
            if e.get("url"):
                k += 1
                e["id"] = f"G{k}"
                sources.append({"id": f"G{k}", "title": e["headline"], "source": e["source"], "url": e["url"],
                                "published": e.get("when_utc", "")})
    ctx = _round_floats(ctx)
    # One entry per URL; ids of duplicates (e.g. a geopolitics event that is also a news item) become aliases so a
    # citation by either id still resolves.
    by_url: dict[str, dict] = {}
    for s in sources:
        if s["url"] in by_url:
            if s.get("id"):
                by_url[s["url"]].setdefault("aliases", []).append(s["id"])
        else:
            by_url[s["url"]] = dict(s)
    return ctx, list(by_url.values())


def _round_floats(o, nd: int = 2):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round_floats(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_round_floats(v, nd) for v in o]
    return o


def context_fingerprint(context: dict, question: str, history: list[dict]) -> str:
    """Stable key for answer caching: same question + same data + same recent turns → same answer."""
    h = hashlib.sha256()
    h.update(question.strip().lower().encode())
    stable = {k: v for k, v in context.items() if k != "question_received_utc"}
    h.update(json.dumps(stable, sort_keys=True, default=str).encode())
    h.update(json.dumps([(m.get("role"), m.get("text")) for m in history[-6:]], default=str).encode())
    return h.hexdigest()[:32]


def _size(obj) -> int:
    return len(json.dumps(obj, default=str, separators=(",", ":")))


def fit_context(context: dict, sources: list[dict], max_chars: int = 9000) -> tuple[dict, list[dict]]:
    """Trim the context to a character budget (free-tier providers cap tokens per request), most expendable first.

    Order: verbose summaries → secondary sections → long tables → fewer news items. The source list is then
    filtered to URLs that are still in the context, so the UI never lists a source the model did not receive.
    """
    import copy
    ctx = copy.deepcopy(context)

    def trim_rows(key: str, n: int) -> None:
        if isinstance(ctx.get(key), list):
            ctx[key] = ctx[key][:n]

    steps = [
        lambda: [n.update(summary=(n.get("summary") or "")[:120]) for n in ctx.get("news", [])],
        lambda: ctx.pop("upcoming_events", None),
        lambda: [t.pop("transmission_framework", None) for t in ctx.get("geopolitics_theaters", []) or []],
        lambda: ctx.get("risk_appetite_checklist", {}) and ctx["risk_appetite_checklist"].pop("signals", None),
        lambda: trim_rows("economic_calendar", 8),
        lambda: ctx.pop("central_banks", None),
        lambda: [n.pop("summary", None) for n in ctx.get("news", [])],
        lambda: ctx.update(markets={k: v[:6] for k, v in ctx.get("markets", {}).items()}),
        lambda: trim_rows("news", 10),
        lambda: ctx.get("gold_drivers") and ctx.update(gold_drivers={k: ctx["gold_drivers"][k] for k in (
            "gold", "reading_1m", "drivers_1m", "structure", "real_yield_10y", "gold_inr_per_10g")
            if k in ctx["gold_drivers"]}),
        lambda: trim_rows("trends_radar", 6),
        lambda: trim_rows("geopolitics_theaters", 3),
        lambda: trim_rows("news", 7),
        lambda: ctx.update(markets={k: v[:4] for k, v in ctx.get("markets", {}).items()}),
        lambda: [c.update(news=c.get("news", [])[:4], recent_quarters=c.get("recent_quarters", [])[-2:])
                 for c in ctx.get("companies", []) or []],
        lambda: trim_rows("news", 5),
    ]
    for step in steps:
        if _size(ctx) <= max_chars:
            break
        step()
    ctx["context_trimmed"] = _size(context) > _size(ctx)
    blob = json.dumps(ctx, default=str)
    def present(s: dict) -> bool:
        ids = [i for i in [s.get("id"), *s.get("aliases", [])] if i]
        return s["url"] in blob and (not ids or any(f'"{i}"' in blob for i in ids))
    return ctx, [s for s in sources if present(s)]
