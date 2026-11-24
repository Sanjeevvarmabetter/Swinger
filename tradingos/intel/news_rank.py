"""Deterministic news prioritisation: cluster near-duplicates, score importance, assign briefing tiers.

The score is a transparent sum (see SCORING_RULES), tuned to the user's stated priorities
(US markets, Indian markets, gold, geopolitics, AI, semiconductors, long-term wealth) without hiding
other major developments: official sources and multi-source corroboration score high regardless of topic.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd

from tradingos.data.news import kw_hit

PRIORITY_TOPICS: dict[str, list[str]] = {
    "Fed & US rates": ["federal reserve", "fed ", "fomc", "powell", "rate cut", "rate hike", "treasury yield"],
    "US equities": ["s&p 500", "nasdaq", "dow ", "wall street", "stocks"],
    "India markets": ["nifty", "sensex", "rbi", "sebi", "rupee", "indian market", "dalal street", "fii", "dii"],
    "Gold & metals": ["gold", "silver", "bullion", "precious metal"],
    "Oil & energy": ["oil", "crude", "opec", "brent", "natural gas", "lng"],
    "Geopolitics": ["tariff", "sanction", "war", "china", "taiwan", "russia", "ukraine", "iran", "israel",
                    "export control", "trade deal", "missile", "ceasefire"],
    "AI & semiconductors": ["ai ", "artificial intelligence", "nvidia", "semiconductor", "chip", "tsmc", "data center",
                            "openai", "anthropic", "gpu"],
    "Inflation & growth": ["inflation", "cpi", "pce", "gdp", "recession", "payroll", "jobs report", "unemployment"],
}
# Routine official notices (operations, circulars, speeches) — primary-source but rarely market-moving.
ROUTINE_OFFICIAL = ["auction", "money market operations", "directions", "amendment", "draft ", "circular",
                    "speech", "remarks", "lessons from", "penalty", "certificate of registration", "treasury bills",
                    "vrr", "repo auction", "weekly statistical", "statistical supplement", "appoint", "conference",
                    "interview", "survey of professional", "working paper", "consultation", "outsourcing",
                    "customer service", "issuance calendar", "lecture", "commercial paper", "h.4.1",
                    "invitation letter", "agenda", "programme of", "background brief", "press kit", "main results",
                    "daily news", "weekly report", "calendar of"]
MARKET_MOVING = ["plunge", "surge", "soar", "tumble", "record high", "record low", "crash", "rally", "selloff",
                 "sell-off", "rate decision", "holds rates", "cuts rates", "raises rates", "emergency", "default",
                 "invade", "attack", "sanctions", "tariff", "ceasefire", "biggest", "worst", "best day"]
MEGA_CAPS = {"AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "TSM", "BRK.B", "JPM"}

SCORING_RULES = [
    ("Official/primary source (central bank, statistics agency, regulator)", "+3"),
    ("Routine official notice (auctions, circulars, speeches, draft directions)", "−3"),
    ("Market-moving language (rate decision, record, plunge, tariff, sanctions…)", "+1"),
    ("Category geopolitics or macro", "+2"),
    ("Category earnings, technology or commodities", "+1"),
    ("Each priority topic matched (max 3)", "+1 each"),
    ("Each additional independent source reporting the same story (max 3)", "+1 each"),
    ("Mentions a mega-cap ticker", "+1"),
    ("Published in the last 12 hours", "+1"),
    ("Labelled speculation / unconfirmed", "−2"),
    ("Labelled analyst opinion", "−1"),
]
TIERS = [(7, "MUST KNOW"), (5, "IMPORTANT"), (3, "INTERESTING"), (-99, "IGNORE FOR NOW")]
STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "by", "with", "is", "are", "from",
        "after", "over", "its", "it", "be", "this", "that", "says", "said", "new", "us", "will"}


# Words too common in market headlines to signal "same story" on their own.
GENERIC = {"stock", "stocks", "share", "shares", "market", "markets", "rally", "investor", "investors", "price",
           "prices", "trade", "trading", "global", "world", "week", "today", "year", "day", "rise", "rises",
           "fall", "falls", "gain", "gains", "higher", "lower", "report", "news", "update", "live", "street", "wall"}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower().replace("'s", "")) if w not in STOP and (len(w) > 2 or (w.isdigit() and len(w) == 2))}


def same_story(a: set[str], b: set[str]) -> bool:
    """Near-duplicate test: high overall overlap, or ≥4 shared distinctive (non-generic) words."""
    if jaccard(a, b) >= 0.45:
        return True
    shared = (a & b) - GENERIC
    return len(shared) >= 4 or (len(shared) >= 3 and jaccard(a, b) >= 0.25)


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def topics_for(text: str) -> list[str]:
    t = f" {text.lower()} "
    return [name for name, kws in PRIORITY_TOPICS.items() if any(kw_hit(t, k) for k in kws)]


def cluster(df: pd.DataFrame) -> pd.DataFrame:
    """Greedy single-pass clustering of near-duplicate headlines (newest first). Adds cluster_id."""
    if df.empty:
        return df.assign(cluster_id=[])
    df = df.sort_values("published_utc", ascending=False).reset_index(drop=True)
    toks = [tokens(h) for h in df["headline"]]
    reps: list[tuple[int, set[str]]] = []
    ids = []
    for i, tk in enumerate(toks):
        cid = next((c for c, rt in reps if same_story(tk, rt)), None)
        if cid is None:
            cid = i
            reps.append((cid, tk))
        ids.append(cid)
    return df.assign(cluster_id=ids)


def score_item(r: dict, n_sources: int, now: datetime) -> tuple[int, list[str]]:
    reasons, s = [], 0
    info = str(r.get("info_type") or "")
    text = f"{r.get('headline', '')} {r.get('summary', '')}"
    low = f" {text.lower()} "
    if info.startswith("Confirmed"):
        s += 3
        reasons.append("official source")
        if any(kw_hit(low, k) for k in ROUTINE_OFFICIAL) and not kw_hit(low, "chair"):
            s -= 3
            reasons.append("routine notice")
    if any(kw_hit(low, k) for k in MARKET_MOVING):
        s += 1
        reasons.append("market-moving")
    cat = r.get("category") or ""
    if cat in ("geopolitics", "macro"):
        s += 2
        reasons.append(cat)
    elif cat in ("earnings", "technology", "commodities"):
        s += 1
        reasons.append(cat)
    tps = topics_for(text)[:3]
    s += len(tps)
    reasons += tps
    extra = min(max(n_sources - 1, 0), 3)
    if extra:
        s += extra
        reasons.append(f"{n_sources} sources")
    tick = set(str(r.get("tickers") or "").split(","))
    if tick & MEGA_CAPS:
        s += 1
        reasons.append("mega-cap")
    pub = r.get("published_utc")
    if pub is not None and pd.notna(pub) and pd.Timestamp(pub).to_pydatetime() >= now - timedelta(hours=12):
        s += 1
    if info.startswith("Speculation"):
        s -= 2
        reasons.append("speculative")
    elif info.startswith("Analyst"):
        s -= 1
    return s, reasons


def tier_for(score: int) -> str:
    return next(label for cut, label in TIERS if score >= cut)


def rank_news(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """One row per story cluster with score, tier, reasons, all sources and links."""
    cols = ["tier", "score", "headline", "source", "published_utc", "url", "category", "region", "info_type",
            "topics", "reasons", "n_sources", "also_reported_by", "other_links", "summary", "impact", "tickers"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    df = cluster(df)
    out = []
    for _, g in df.groupby("cluster_id", sort=False):
        g = g.copy()
        # Representative: prefer an official source, then the earliest report (original), else newest.
        g["_off"] = g["info_type"].astype(str).str.startswith("Confirmed")
        rep = g.sort_values(["_off", "published_utc"], ascending=[False, True]).iloc[0].to_dict()
        sources = list(dict.fromkeys(g["source"]))
        sc, reasons = score_item(rep, len(sources), now)
        out.append({
            **{k: rep.get(k) for k in ("headline", "source", "published_utc", "url", "category", "region",
                                       "info_type", "summary", "impact", "tickers")},
            "score": sc, "tier": tier_for(sc), "topics": ", ".join(topics_for(f"{rep['headline']} {rep.get('summary', '')}")),
            "reasons": ", ".join(reasons), "n_sources": len(sources),
            "also_reported_by": ", ".join(s for s in sources if s != rep["source"]),
            "other_links": [u for u in g["url"].tolist() if u and u != rep.get("url")][:3],
        })
    res = pd.DataFrame(out)
    tier_order = {label: i for i, (_, label) in enumerate(TIERS)}
    res["_t"] = res["tier"].map(tier_order)
    return res.sort_values(["_t", "score", "published_utc"], ascending=[True, False, False]).drop(columns="_t") \
              .reset_index(drop=True)[cols]


def threads(df: pd.DataFrame, now: datetime | None = None, min_items: int = 2) -> pd.DataFrame:
    """Story threads: near-duplicate clusters over a longer window, with first/last seen and how the story evolved.
    Only threads with at least `min_items` stored items are returned (single items are not 'developing')."""
    cols = ["headline", "tier", "score", "first_seen", "last_seen", "span_hours", "n_items", "n_sources", "sources",
            "region", "topics", "timeline"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    c = cluster(df)
    ranked = {r["headline"]: r for _, r in rank_news(df, now=now).iterrows()}
    out = []
    for _, g in c.groupby("cluster_id", sort=False):
        if len(g) < min_items:
            continue
        g = g.sort_values("published_utc")
        rep = g[g["headline"].isin(ranked)].iloc[0] if g["headline"].isin(ranked).any() else g.iloc[0]
        rr = ranked.get(rep["headline"], {})
        first, last = pd.Timestamp(g["published_utc"].min()), pd.Timestamp(g["published_utc"].max())
        out.append({"headline": rep["headline"], "tier": rr.get("tier", ""), "score": rr.get("score", 0),
                    "first_seen": first, "last_seen": last, "span_hours": round((last - first).total_seconds() / 3600, 1),
                    "n_items": len(g), "n_sources": g["source"].nunique(), "sources": ", ".join(dict.fromkeys(g["source"])),
                    "region": rep.get("region", ""), "topics": ", ".join(topics_for(f"{rep['headline']} {rep.get('summary') or ''}")),
                    "timeline": [{"published_utc": pd.Timestamp(x["published_utc"]).strftime("%Y-%m-%d %H:%M"),
                                  "source": x["source"], "headline": x["headline"], "url": x["url"]}
                                 for _, x in g.iterrows()]})
    res = pd.DataFrame(out, columns=cols)
    return res.sort_values(["n_sources", "last_seen"], ascending=[False, False]).reset_index(drop=True)
