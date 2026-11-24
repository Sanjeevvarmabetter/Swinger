"""Geopolitical intelligence: theaters, event cards, attention trends, market reaction, timeline and map data.

Two kinds of content, kept separate and labelled in the UI:
  * EVIDENCE (computed): which stored news stories match a theater, how many independent sources, official vs
    reported vs speculative, attention now vs the prior weeks, and how the linked markets moved.
  * FRAMEWORK (static, analytical): the usual transmission channels, exposed sectors/commodities/countries and
    what to monitor for each theater. It is context for interpretation — not a claim about what is happening now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from tradingos.data.news import kw_hit
from tradingos.intel import entities
from tradingos.intel.news_rank import rank_news


@dataclass(frozen=True)
class Theater:
    key: str
    name: str
    keywords: tuple[str, ...]
    lat: float
    lon: float
    countries: tuple[str, ...]
    sectors: tuple[str, ...]
    commodities: tuple[str, ...]
    instruments: tuple[str, ...]          # registry symbols used to show market reaction
    channels: str
    watch: str
    exclude: tuple[str, ...] = field(default_factory=tuple)


THEATERS: list[Theater] = [
    Theater("us_china", "US–China relations", ("us-china", "u.s.-china", "beijing", "xi jinping", "china tariff",
            "chinese exports", "trade truce", "trade talks with china"), 35.0, 116.0,
            ("United States", "China"), ("Semiconductors", "Consumer electronics", "Industrials", "Agriculture"),
            ("Soybeans", "Rare earths", "Copper"), ("^HSI", "000001.SS", "KWEB", "SMH", "HG=F"),
            "Tariffs and export controls hit trade volumes, corporate margins and supply chains; risk-off moves lift "
            "the dollar and pressure EM equities; retaliation via rare earths or agricultural purchases.",
            "Tariff deadlines, export-control rule changes, rare-earth licensing, leader meetings, Chinese stimulus."),
    Theater("taiwan", "China–Taiwan", ("taiwan", "taiwan strait", "taipei", "pla drills"), 23.7, 121.0,
            ("China", "Taiwan", "United States", "Japan"), ("Semiconductors", "Electronics supply chain", "Shipping"),
            ("—",), ("TSM", "SMH", "^N225", "^KS11"),
            "Taiwan makes most leading-edge chips: any blockade or escalation risk feeds directly into semiconductor "
            "supply expectations, tech valuations and shipping insurance through the strait.",
            "PLA exercises, US arms sales, Taiwanese political events, TSMC guidance and overseas fab progress."),
    Theater("russia_ukraine", "Russia–Ukraine", ("ukraine", "ukrainian", "kyiv", "kremlin", "putin", "zelensky",
            "zelenskiy", "donbas", "crimea"), 49.0, 32.0, ("Russia", "Ukraine", "European Union", "United States"),
            ("Energy", "Defence", "Agriculture", "European industrials"), ("Natural gas", "Wheat", "Oil", "Fertiliser"),
            ("NG=F", "ZW=F", "BZ=F", "ITA", "^GDAXI"),
            "Energy supply to Europe (gas prices → industrial costs, inflation), grain exports through the Black Sea, "
            "sanctions on Russian oil, European defence spending.",
            "Ceasefire talks, strikes on energy infrastructure, new sanctions/price-cap enforcement, Black Sea shipping."),
    Theater("middle_east", "Middle East & Israel–Palestine", ("israel", "israeli", "gaza", "hamas", "hezbollah",
            "west bank", "netanyahu", "lebanon", "houthi", "houthis", "red sea"), 31.5, 35.0,
            ("Israel", "Palestine / Gaza", "Lebanon", "Yemen", "Egypt", "Saudi Arabia"),
            ("Energy", "Shipping", "Defence", "Airlines"), ("Oil", "Gold"), ("BZ=F", "GC=F", "ITA", "^TNX"),
            "Escalation risks oil supply and Red Sea/Suez shipping (freight costs, delivery times, inflation); "
            "safe-haven demand for gold and Treasuries; defence orders.",
            "Ceasefire status, Red Sea shipping attacks, Suez transits, involvement of regional states."),
    Theater("iran", "Iran", ("iran", "iranian", "tehran", "hormuz", "irgc"), 32.0, 53.0,
            ("Iran", "Israel", "United States", "Saudi Arabia", "UAE"), ("Energy", "Shipping", "Defence"),
            ("Oil", "Natural gas (LNG)", "Gold"), ("BZ=F", "CL=F", "GC=F", "ITA"),
            "About a fifth of seaborne oil passes the Strait of Hormuz: disruption or sanctions changes oil supply, "
            "freight and inflation; India is especially exposed through its oil import bill.",
            "Hormuz tanker traffic, nuclear talks, sanctions enforcement on Iranian exports, strikes and retaliation."),
    Theater("us_foreign_policy", "US foreign policy", ("white house", "state department", "secretary of state",
            "trump administration", "executive order", "us sanctions", "u.s. sanctions"), 38.9, -77.0,
            ("United States",), ("Defence", "Trade-exposed sectors"), ("—",), ("DX-Y.NYB", "^GSPC", "ITA"),
            "Executive actions on trade, sanctions and alliances change tariffs, defence demand and the dollar.",
            "Executive orders, sanctions designations, summit outcomes, Congressional funding votes."),
    Theater("nato_eu", "NATO & European Union", ("nato", "european union", "european commission", "brussels",
            "eu leaders", "eu sanctions"), 50.8, 4.4, ("European Union", "Germany", "France", "United Kingdom"),
            ("Defence", "Autos", "Energy"), ("Natural gas",), ("^STOXX50E", "^GDAXI", "EURUSD=X", "ITA"),
            "European rearmament budgets, EU trade measures and fiscal rules drive defence stocks, the euro and bunds.",
            "NATO spending targets, EU tariff/countermeasure decisions, EU budget and fiscal-rule changes."),
    Theater("india_china", "India–China", ("india-china", "india china", "lac ", "ladakh", "galwan", "arunachal"),
            34.0, 78.5, ("India", "China"), ("Electronics manufacturing", "Pharma (API imports)", "Defence"),
            ("—",), ("^NSEI", "INR=X"),
            "Border tensions or thaws affect Chinese investment rules, component/API imports and India's "
            "China+1 manufacturing narrative.",
            "Border talks, investment-rule (Press Note 3) changes, direct flights/visas, import restrictions."),
    Theater("india_pakistan", "India–Pakistan", ("pakistan", "pakistani", "islamabad", "kashmir", "line of control",
            "loc ", "indus waters"), 33.5, 74.0, ("India", "Pakistan"), ("Defence", "Indian equities broadly"),
            ("—",), ("^NSEI", "^INDIAVIX", "INR=X"),
            "Military escalation historically lifts India VIX and defence stocks and hurts broad risk appetite briefly; "
            "markets usually focus on whether escalation is contained.",
            "Cross-border incidents, official statements from both governments, Indus Waters Treaty actions."),
    Theater("trade_tariffs", "Trade wars & tariffs", ("tariff", "tariffs", "trade war", "trade deal", "import duty",
            "countermeasures", "section 232", "section 301", "reciprocal"), 40.7, -74.0,
            ("United States", "China", "European Union", "India", "Mexico", "Canada"),
            ("Autos", "Retail", "Semiconductors", "Agriculture", "Steel & aluminium"), ("Steel", "Aluminium", "Copper"),
            ("^GSPC", "DX-Y.NYB", "HG=F", "^NSEI"),
            "Tariffs raise input costs and consumer prices, shift trade flows and margins; they can strengthen the "
            "dollar and weigh on exporters' currencies.",
            "Tariff effective dates, exemptions, retaliation, court rulings on tariff authority, trade-deal texts."),
    Theater("sanctions", "Sanctions", ("sanction", "sanctions", "ofac", "price cap", "blacklist", "asset freeze"),
            55.7, 37.6, ("Russia", "Iran", "Venezuela", "China"), ("Energy", "Banks", "Shipping"), ("Oil", "Metals"),
            ("BZ=F", "GC=F"),
            "Sanctions re-route commodity flows (discounts, freight), restrict banks and can tighten supply of oil "
            "and metals.",
            "New designations, secondary-sanction enforcement on buyers (incl. Indian refiners), price-cap changes."),
    Theater("elections", "Elections & political transitions", ("election", "elections", "polls", "vote count",
            "snap election", "referendum", "coalition"), 48.0, 10.0, (), ("Policy-sensitive sectors",), ("—",),
            ("^GSPC", "^NSEI", "^STOXX50E"),
            "Elections change fiscal, trade and regulatory expectations; uncertainty tends to raise volatility before "
            "results.",
            "Polling, result dates, coalition talks, policy platforms on tax, trade and spending."),
    Theater("energy_shipping", "Energy security & shipping routes", ("strait of hormuz", "hormuz", "red sea",
            "suez", "panama canal", "shipping lane", "tanker", "freight rates", "lng supply", "pipeline"),
            12.5, 43.5, ("Egypt", "Yemen", "Iran", "Panama"), ("Shipping", "Energy", "Retail (import costs)"),
            ("Oil", "LNG", "Container freight"), ("BZ=F", "NG=F", "^TNX"),
            "Chokepoint disruptions lengthen voyages, raise freight and insurance and add to goods inflation; LNG "
            "outages raise European and Asian gas prices.",
            "Transit counts through Hormuz/Suez/Panama, attacks on vessels, insurance premia, LNG plant outages."),
    Theater("critical_minerals", "Critical minerals", ("rare earth", "rare earths", "critical mineral", "lithium",
            "cobalt", "gallium", "germanium", "graphite", "antimony"), -15.0, 28.0,
            ("China", "United States", "Australia", "Indonesia"), ("EVs", "Defence", "Electronics"),
            ("Rare earths", "Lithium", "Copper"), ("REMX", "MP", "HG=F"),
            "China dominates processing; export licensing can choke supply to EV, defence and electronics makers "
            "and boost non-China producers.",
            "Chinese export-licence decisions, Western offtake deals and subsidies, price floors."),
    Theater("chip_controls", "Semiconductor export controls", ("export control", "export controls", "entity list",
            "chip ban", "chip export", "huawei", "smic", "nvidia china", "h20"), 37.4, -122.0,
            ("United States", "China", "Netherlands", "Japan", "Taiwan"), ("Semiconductors", "Semi equipment"),
            ("—",), ("SMH", "NVDA", "ASML", "AMAT", "KWEB"),
            "Controls cut chipmakers' and equipment makers' China revenue and accelerate Chinese substitution.",
            "BIS rule updates, licence approvals, allied (Dutch/Japanese) alignment, Chinese retaliation."),
    Theater("military", "Military developments (global)", ("military", "missile", "airstrike", "air strike",
            "drone attack", "troops", "invasion", "warship", "naval"), 20.0, 0.0, (), ("Defence",),
            ("Oil", "Gold"), ("ITA", "GC=F", "^VIX"),
            "Military escalation raises safe-haven demand (gold, Treasuries, dollar), volatility and defence demand.",
            "Escalation vs de-escalation signals, casualty counts, involvement of major powers."),
]
THEATER_BY_KEY = {t.key: t for t in THEATERS}

FRAMEWORK_NOTE = ("Framework (static analysis, not news): typical transmission channels and exposures for this theater. "
                  "Use it to interpret the evidence below — it does not say anything is happening now.")


def match_theaters(text: str) -> list[str]:
    t = f" {text} "
    return [th.key for th in THEATERS if any(kw_hit(t, k) for k in th.keywords)
            and not any(kw_hit(t, x) for x in th.exclude)]


def tag_news(df: pd.DataFrame) -> pd.DataFrame:
    """Add `theaters` (list) to each news row; keep only rows matching at least one theater."""
    if df is None or df.empty:
        return pd.DataFrame(columns=[*(df.columns if df is not None else []), "theaters"])
    d = df.copy()
    d["theaters"] = [match_theaters(f"{h} {s or ''}") for h, s in zip(d["headline"], d["summary"])]
    return d[d["theaters"].map(len) > 0].reset_index(drop=True)


MIN_BASE_STORIES = 4   # fewer stories in the whole 28-day baseline → ratio is noise, not reported


def collecting_since(df: pd.DataFrame) -> datetime | None:
    """Earliest retrieval time in the stored news (when the app started collecting)."""
    if df is None or df.empty or "retrieved_utc" not in df.columns:
        return None
    v = pd.to_datetime(df["retrieved_utc"]).min()
    return None if pd.isna(v) else v.to_pydatetime()


def baseline_ready(since: datetime | None, now: datetime, recent_days: int = 7, base_days: int = 28) -> bool:
    """A 7d-vs-prior-28d comparison is only meaningful once the app has collected for the full 35 days —
    RSS feeds expose just a few days of history, so an early 'baseline' would be mostly empty."""
    return since is not None and (now - since) >= timedelta(days=recent_days + base_days)


def attention(tagged: pd.DataFrame, now: datetime, recent_days: int = 7, base_days: int = 28,
              since: datetime | None = None) -> pd.DataFrame:
    """Per theater: stories in the recent window vs the weekly average of the preceding base window.
    The ratio is withheld (None, 'Building baseline') until collection has run long enough."""
    since = since if since is not None else collecting_since(tagged)
    ready = baseline_ready(since, now, recent_days, base_days)
    rows = []
    for th in THEATERS:
        sub = tagged[tagged["theaters"].map(lambda x: th.key in x)] if len(tagged) else tagged
        pub = pd.to_datetime(sub["published_utc"]) if len(sub) else pd.Series(dtype="datetime64[ns]")
        recent = int((pub >= now - timedelta(days=recent_days)).sum())
        base = int(((pub < now - timedelta(days=recent_days)) & (pub >= now - timedelta(days=recent_days + base_days))).sum())
        base_rate = base / (base_days / recent_days)
        ratio = round(recent / base_rate, 2) if ready and base >= MIN_BASE_STORIES else None
        if not ready:
            trend = "Building baseline" if recent else "Quiet"
        elif ratio is None:
            trend = "Too few prior stories" if recent else "Quiet"
        else:
            trend = "Rising" if ratio >= 1.5 else "Falling" if ratio <= 0.67 else "Steady"
        rows.append({"key": th.key, "Theater": th.name, f"Stories {recent_days}d": recent,
                     "Prior weekly avg": round(base_rate, 1) if ready else None, "Attention ratio": ratio,
                     "Trend": trend, "lat": th.lat, "lon": th.lon})
    return pd.DataFrame(rows)


def event_cards(tagged: pd.DataFrame, theater_key: str, now: datetime, days: int = 7, n: int = 12) -> list[dict]:
    """Answer the 11 standard questions for each clustered story in a theater, from evidence only."""
    th = THEATER_BY_KEY[theater_key]
    sub = tagged[tagged["theaters"].map(lambda x: theater_key in x)] if len(tagged) else tagged
    if len(sub):
        sub = sub[pd.to_datetime(sub["published_utc"]) >= now - timedelta(days=days)]
    ranked = rank_news(sub.drop(columns=["theaters"]) if len(sub) else sub, now=now)
    cards = []
    for _, r in ranked.head(n).iterrows():
        text = f"{r['headline']} {r.get('summary') or ''}"
        ents = entities.extract(text)
        info = str(r["info_type"])
        if info.startswith("Confirmed"):
            confirmed = "Official/primary source."
        elif r["n_sources"] >= 2 and not info.startswith("Speculation"):
            confirmed = f"Reported by {r['n_sources']} independent outlets."
        else:
            confirmed = "Single-source report — not independently corroborated in stored feeds."
        uncertain = []
        if info.startswith("Speculation"):
            uncertain.append("Wording is speculative (e.g. 'could', 'reportedly', 'sources say').")
        if info.startswith("Analyst"):
            uncertain.append("Contains opinion/analysis rather than a reported event.")
        if r["n_sources"] < 2 and not info.startswith("Confirmed"):
            uncertain.append("Only one source so far.")
        cards.append({
            "tier": r["tier"], "score": int(r["score"]), "headline": r["headline"], "url": r["url"],
            "source": r["source"], "also_reported_by": r["also_reported_by"], "other_links": r["other_links"],
            "what_happened": r["headline"] + (f" — {r['summary'][:220]}" if r.get("summary") else ""),
            "when_utc": pd.Timestamp(r["published_utc"]).strftime("%Y-%m-%d %H:%M") if pd.notna(r["published_utc"]) else None,
            "who": ents["countries"] + ents["institutions"],
            "confirmed": confirmed, "uncertain": " ".join(uncertain) or "No uncertainty markers detected in the text "
                                                                          "(still verify with the source).",
            "info_type": info,
            "why_it_matters_framework": th.channels,
            "countries_affected": sorted(set(ents["countries"]) | set(th.countries)),
            "sectors_framework": list(th.sectors), "commodities_framework": [c for c in th.commodities if c != "—"],
            "monitor_next_framework": th.watch,
        })
    return cards


def market_reaction(snap: pd.DataFrame, theater_key: str) -> pd.DataFrame:
    from tradingos.intel.markets import row
    th = THEATER_BY_KEY[theater_key]
    rows = []
    for s in th.instruments:
        r = row(snap, s)
        if r:
            rows.append({"Instrument": r["Name"], "Symbol": s, "Last": r["Last"], "1D %": r["1D %"], "1W %": r["1W %"],
                         "1M %": r["1M %"], "Last bar": r["Last bar"], "Freshness": r["Freshness"]})
        else:
            rows.append({"Instrument": s, "Symbol": s, "Last": None, "1D %": None, "1W %": None, "1M %": None,
                         "Last bar": None, "Freshness": "not in market snapshot"})
    return pd.DataFrame(rows)


def timeline(tagged: pd.DataFrame, now: datetime, days: int = 30) -> pd.DataFrame:
    """One row per (story cluster, theater) for the risk timeline."""
    if tagged is None or tagged.empty:
        return pd.DataFrame(columns=["published_utc", "Theater", "headline", "tier", "score", "source", "url", "n_sources"])
    recent = tagged[pd.to_datetime(tagged["published_utc"]) >= now - timedelta(days=days)]
    ranked = rank_news(recent.drop(columns=["theaters"]), now=now)
    rows = []
    for _, r in ranked.iterrows():
        for k in match_theaters(f"{r['headline']} {r.get('summary') or ''}"):
            rows.append({"published_utc": r["published_utc"], "Theater": THEATER_BY_KEY[k].name, "headline": r["headline"],
                         "tier": r["tier"], "score": r["score"], "source": r["source"], "url": r["url"],
                         "n_sources": r["n_sources"]})
    return pd.DataFrame(rows)


def summary_for_briefing(tagged: pd.DataFrame, now: datetime, top: int = 6) -> list[dict]:
    att = attention(tagged, now).sort_values("Stories 7d", ascending=False)
    out = []
    for _, a in att.head(top).iterrows():
        if a["Stories 7d"] == 0:
            continue
        cards = event_cards(tagged, a["key"], now, days=7, n=3)
        out.append({"theater": a["Theater"], "stories_7d": int(a["Stories 7d"]), "attention_ratio": a["Attention ratio"],
                    "trend": a["Trend"], "top_events": [{k: c[k] for k in ("tier", "headline", "url", "source", "when_utc",
                                                                           "confirmed", "uncertain")} for c in cards],
                    "transmission_framework": THEATER_BY_KEY[a["key"]].channels})
    return out


def now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
