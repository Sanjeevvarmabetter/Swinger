"""Daily intelligence briefings: editions, schedule, payload assembly, deterministic + Gemini editions, archive.

Pipeline for one edition:
  1. (optional) refresh news feeds
  2. build_payload(): cross-market snapshot, risk checklist, gold drivers, ranked news, calendars, data quality
  3. deterministic_markdown(): a complete factual briefing that needs no AI (always produced)
  4. Gemini "Daily Briefing Editor" writes the readable edition from the same payload (if configured)
  5. both are archived in the `briefings` table
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from tradingos.db.models import Briefing
from tradingos.db.session import session_scope

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Edition:
    key: str
    title: str
    local_time: time
    tz: ZoneInfo
    weekdays: tuple[int, ...]       # 0=Mon … 6=Sun
    news_days: int
    focus: str
    monthly: bool = False           # only on the 1st of the month


EDITIONS: dict[str, Edition] = {e.key: e for e in [
    Edition("global_morning", "Global Morning Briefing", time(7, 0), IST, (0, 1, 2, 3, 4, 5), 1,
            "overnight US close, Asia open, gold, geopolitics and anything that happened while the reader slept"),
    Edition("india_open", "Indian Market Opening Briefing", time(8, 30), IST, (0, 1, 2, 3, 4), 1,
            "what matters for today's NSE/BSE session: global cues, USD/INR, crude, Indian news, RBI/SEBI, sectors"),
    Edition("india_close", "Indian Market Closing Report", time(16, 15), IST, (0, 1, 2, 3, 4), 1,
            "how Indian markets closed, sector leadership, breadth across caps, Indian news and Europe's open"),
    Edition("us_premarket", "US Pre-Market Briefing", time(7, 30), ET, (0, 1, 2, 3, 4), 1,
            "set-up for the US session: futures-relevant news, today's US data and earnings, Europe, rates, dollar"),
    Edition("us_close", "US Market Closing Report", time(16, 30), ET, (0, 1, 2, 3, 4), 1,
            "how US markets closed, sector/theme leadership, breadth, rates, after-hours earnings"),
    Edition("weekly_review", "Weekly Global Market Review", time(9, 0), IST, (5,), 7,
            "the week's biggest developments across all regions, what changed, and next week's calendar"),
    Edition("monthly_review", "Monthly Macro & Investment Trends Report", time(9, 0), IST, tuple(range(7)), 31,
            "the month's macro and market trends, structural themes, and the outlook risks", monthly=True),
]}


# ----------------------------------------------------------------------------- schedule
def scheduled_at(ed: Edition, on: date) -> datetime:
    """UTC datetime of the edition on local calendar date `on` (DST handled by zoneinfo)."""
    return datetime.combine(on, ed.local_time, tzinfo=ed.tz).astimezone(timezone.utc)


def edition_date_for(ed: Edition, now: datetime) -> date:
    return scheduled_at(ed, now.astimezone(ed.tz).date()).astimezone(IST).date()


def runs_on(ed: Edition, local_day: date) -> bool:
    if ed.monthly:
        return local_day.day == 1
    return local_day.weekday() in ed.weekdays


def next_runs(now: datetime | None = None, days: int = 2) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for ed in EDITIONS.values():
        local_today = now.astimezone(ed.tz).date()
        for k in range(days + 1):
            d = local_today + timedelta(days=k)
            at = scheduled_at(ed, d)
            if runs_on(ed, d) and at >= now:
                out.append({"edition": ed.key, "title": ed.title, "at_utc": at,
                            "at_ist": at.astimezone(IST).strftime("%a %d %b %H:%M IST")})
                break
    return sorted(out, key=lambda r: r["at_utc"])


def due_editions(now: datetime | None = None, grace_hours: float = 3.0) -> list[str]:
    """Editions whose scheduled time has passed within the grace window and that are not yet archived."""
    now = now or datetime.now(timezone.utc)
    due = []
    for ed in EDITIONS.values():
        local_day = now.astimezone(ed.tz).date()
        if not runs_on(ed, local_day):
            continue
        at = scheduled_at(ed, local_day)
        if at <= now <= at + timedelta(hours=grace_hours):
            if latest(ed.key, edition_date=at.astimezone(IST).date()) is None:
                due.append(ed.key)
    return due


# ----------------------------------------------------------------------------- payload
def _compact(df: pd.DataFrame, cols=("Name", "Last", "1D %", "1W %", "1M %", "YTD %", "Last bar", "Freshness")) -> list[dict]:
    if df is None or df.empty:
        return []
    d = df[[c for c in cols if c in df.columns]].copy()
    for c in ("1D %", "1W %", "1M %", "3M %", "YTD %", "1Y %"):
        if c in d.columns:
            d[c] = d[c].astype(float).round(2)
    return d.where(pd.notna(d), None).to_dict("records")


def build_payload(edition: str, force: bool = False, now: datetime | None = None) -> dict:
    from tradingos.data.macro import MACRO_SERIES, get_series
    from tradingos.data.news import query_news
    from tradingos.intel import calendars, gold, markets
    from tradingos.intel.instruments import MAG7, UNAVAILABLE
    from tradingos.intel.news_rank import SCORING_RULES, rank_news

    ed = EDITIONS[edition]
    now = now or datetime.now(timezone.utc)
    snap, meta = markets.snapshot(force=force, now=now)
    hy = next((m for m in MACRO_SERIES if m.sid == "BAMLH0A0HYM2"), None)
    hy_res = get_series(hy) if hy else None
    hy_val = float(hy_res.data.iloc[-1]) if hy_res is not None and hy_res.ok and len(hy_res.data) else None
    risk = markets.risk_appetite(snap, hy_val)

    res = markets.load_histories()
    closes = {s: f["Close"].dropna() for s, f in (res.data or {}).items()}
    gold_ctx = gold.gold_context(snap, closes, force=force)

    news = query_news(days=ed.news_days + 1, limit=600)
    ranked = rank_news(news, now=now.replace(tzinfo=None))
    news_items = []
    for _, r in ranked.head(60).iterrows():
        news_items.append({
            "tier": r["tier"], "score": int(r["score"]), "headline": r["headline"], "source": r["source"],
            "published_utc": pd.Timestamp(r["published_utc"]).strftime("%Y-%m-%d %H:%M") if pd.notna(r["published_utc"]) else None,
            "url": r["url"], "category": r["category"], "region": r["region"], "info_type": r["info_type"],
            "topics": r["topics"], "n_sources": int(r["n_sources"]), "also_reported_by": r["also_reported_by"],
            "summary": (r["summary"] or "")[:280], "rule_based_impact_note": r["impact"] or None,
        })

    events, ev_errs = calendars.combined_events(days=7 if ed.news_days <= 1 else 14)
    stage2, s2_errs = _stage2_sections(now, ed)
    watch = set(MAG7.values())
    try:
        from tradingos.data.providers import load_universe
        watch |= set(load_universe()["ticker"])
    except Exception:  # noqa: BLE001
        pass
    earn = calendars.earnings_calendar(days=7, symbols=watch)

    g = lambda name: _compact(markets.group(snap, name))  # noqa: E731
    sectors = markets.group(snap, "US sectors").sort_values("1W %", ascending=False)
    themes = markets.group(snap, "US themes").sort_values("1W %", ascending=False)
    in_sec = markets.group(snap, "India sectors").sort_values("1W %", ascending=False)

    return {
        "edition": {"key": ed.key, "title": ed.title, "focus": ed.focus,
                    "generated_at_utc": now.strftime("%Y-%m-%d %H:%M UTC"),
                    "generated_at_ist": now.astimezone(IST).strftime("%a %d %b %Y %H:%M IST"),
                    "news_window_days": ed.news_days},
        "market_data_meta": meta,
        "risk_appetite": risk,
        "markets": {
            "us_indices": g("US indices"), "volatility": g("Volatility"), "us_yields": g("US Treasury yields"),
            "credit_bonds": g("Credit & bonds"), "currencies": g("Currencies"), "europe": g("Europe"),
            "asia_pacific": g("Asia-Pacific"), "india": g("India"), "precious_metals": g("Precious metals"),
            "energy_industrial": g("Energy & industrial"), "crypto": g("Crypto"), "magnificent_7": g("Magnificent 7"),
            "us_sectors_by_1w": _compact(sectors), "us_themes_by_1w": _compact(themes),
            "india_sectors_by_1w": _compact(in_sec),
        },
        "gold": gold_ctx,
        "news_ranked": news_items,
        "news_scoring_rules": SCORING_RULES,
        "news_counts_by_region": ranked["region"].value_counts().to_dict() if len(ranked) else {},
        "upcoming_events": _events_records(events),
        "upcoming_earnings_watchlist": earn.data.head(40).to_dict("records") if earn.ok and len(earn.data) else [],
        **stage2,
        "data_quality": {
            "freshness_counts": markets.freshness_summary(snap),
            "missing_symbols": meta.get("missing", []),
            "errors": [e for e in [meta.get("error"), *ev_errs, earn.error, *gold_ctx.get("errors", []), *s2_errs] if e],
            "not_available_in_this_app": [{"item": n, "why": w, "official_link": u} for n, w, u in UNAVAILABLE],
            "x_twitter": _x_status(),
        },
        "x_intelligence": _x_section(),
    }


def _x_section() -> dict:
    try:
        from tradingos.intel import xintel
        return xintel.briefing_section()
    except Exception as e:  # noqa: BLE001
        return {"status": f"X data unavailable: {type(e).__name__}"}


def _x_status() -> str:
    return _x_section().get("status", "")


def _stage2_sections(now: datetime, ed: Edition) -> tuple[dict, list[str]]:
    """Geopolitics theaters, trends radar, economic calendar with readings, central banks. Each part fails soft."""
    from tradingos.data.news import query_news
    from tradingos.intel import calendars, geopolitics, trends
    out, errs = {}, []
    naive = now.astimezone(timezone.utc).replace(tzinfo=None)
    news = query_news(days=35, limit=5000)
    try:
        out["geopolitics"] = geopolitics.summary_for_briefing(geopolitics.tag_news(news), naive)
    except Exception as e:
        errs.append(f"geopolitics: {e}")
    try:
        tab, _, _ = trends.radar(news, naive)
        out["trends_radar"] = trends.briefing_rows(tab)
        out["trends_methodology"] = [f"{k}: {v}" for k, v in trends.METHODOLOGY]
    except Exception as e:
        errs.append(f"trends: {e}")
    try:
        cal, cerr = calendars.economic_calendar(past_days=3 if ed.news_days <= 1 else 7,
                                                ahead_days=7 if ed.news_days <= 1 else 14)
        errs += cerr
        rows = []
        for _, r in cal.iterrows():
            rec = {k: (str(r[k]) if k == "date" else r[k]) for k in ("date", "time_ist", "country", "event", "importance",
                                                                    "source", "market_relevance") if k in cal.columns}
            if pd.notna(r.get("rid")) and r["importance"] in ("high", "medium"):
                rec["readings"] = calendars.release_readings(int(r["rid"]), r["date"], superseded=bool(r.get("superseded")))
                rec["forecast"] = "not available (no licensed consensus source)"
            rows.append(rec)
        out["economic_calendar"] = rows
    except Exception as e:
        errs.append(f"economic calendar: {e}")
    try:
        cbs = calendars.central_bank_tracker()
        for cb in cbs:
            cb["latest_communications"] = [{"published_utc": str(c["published_utc"])[:16], "headline": c["headline"],
                                            "url": c["url"], "routine": bool(c["routine"])}
                                           for c in cb.get("latest_communications", [])[:4]]
        out["central_banks"] = cbs
    except Exception as e:
        errs.append(f"central banks: {e}")
    return out, errs


def _events_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    d = df.copy()
    d["date"] = d["date"].astype(str)
    keep = [c for c in ("date", "time_ist", "event", "country", "importance", "source") if c in d.columns]
    return d[keep].to_dict("records")


SHORT_FRESH = {"Intraday (delayed — not real-time)": "intraday-delayed", "Current (latest completed session)": "current",
               "Stale": "STALE", "Very stale": "VERY STALE", "Missing": "MISSING"}


def ai_payload(p: dict, max_stories: int = 40) -> dict:
    """Compact copy of the payload for Gemini (token budget): top-tier stories only, short summaries and
    freshness codes. The full payload is still archived with the briefing for audit."""
    import copy
    q = copy.deepcopy(p)
    for rows in q["markets"].values():
        for r in rows:
            r["Freshness"] = SHORT_FRESH.get(r.get("Freshness"), r.get("Freshness"))
    keep = [n for n in q["news_ranked"] if n["tier"] in ("MUST KNOW", "IMPORTANT")][:30]
    keep += [n for n in q["news_ranked"] if n["tier"] == "INTERESTING"][: max(0, max_stories - len(keep))]
    q["news_ranked"] = [{k: (v[:160] if k == "summary" and v else v) for k, v in n.items()
                         if k not in ("score", "also_reported_by")} for n in keep]
    q["news_ignored_count"] = sum(n["tier"] == "IGNORE FOR NOW" for n in p["news_ranked"])
    q.pop("news_scoring_rules", None)
    q.pop("trends_methodology", None)
    if q.get("trends_radar"):
        q["trends_radar"] = [{k: v for k, v in r.items() if k != "Evidence"} for r in q["trends_radar"]]
    q["economic_calendar"] = [e for e in q.get("economic_calendar", []) if e.get("importance") != "low"]
    q["data_quality"]["not_available_in_this_app"] = [x["item"] for x in q["data_quality"]["not_available_in_this_app"]]
    return q


# ----------------------------------------------------------------------------- deterministic edition
def _pct(v) -> str:
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:+.2f}%"


def _num(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.2f}" if abs(v) < 1e5 else f"{v:,.0f}"


def _table(rows: list[dict], title: str) -> list[str]:
    if not rows:
        return [f"_{title}: no data available._", ""]
    out = [f"**{title}**", "", "| Instrument | Last | 1D | 1W | 1M | YTD | Last bar | Freshness |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['Name']} | {_num(r.get('Last'))} | {_pct(r.get('1D %'))} | {_pct(r.get('1W %'))} | "
                   f"{_pct(r.get('1M %'))} | {_pct(r.get('YTD %'))} | {r.get('Last bar') or '—'} | {r.get('Freshness')} |")
    return out + [""]


def _news_line(n: dict) -> str:
    tag = {"Confirmed": "FACT", "Reported": "REPORTED", "Analyst": "OPINION", "Speculation": "UNVERIFIED"}
    t = next((v for k, v in tag.items() if str(n.get("info_type", "")).startswith(k)), "REPORTED")
    extra = f" · also: {n['also_reported_by']}" if n.get("also_reported_by") else ""
    note = f"\n  - _Rule-based impact note (interpretation):_ {n['rule_based_impact_note']}" if n.get("rule_based_impact_note") else ""
    return (f"- **[{t}]** [{n['headline']}]({n['url']}) — {n['source']}, {n.get('published_utc') or 'time n/a'} UTC"
            f" · {n.get('region')} · {n.get('topics') or n.get('category')}{extra}{note}")


def deterministic_markdown(p: dict) -> str:
    ed = p["edition"]
    L = [f"# {ed['title']}", f"_{ed['generated_at_ist']} · market data: {p['market_data_meta']['source']}, retrieved "
         f"{p['market_data_meta']['retrieved_at_utc']} · news window {ed['news_window_days']}d_", "",
         "> Deterministic edition: every line below is sourced data or a fixed rule. No AI interpretation.", ""]
    news = p["news_ranked"]
    for tier, icon in (("MUST KNOW", "🔴"), ("IMPORTANT", "🟠"), ("INTERESTING", "🔵")):
        items = [n for n in news if n["tier"] == tier]
        cap = {"MUST KNOW": 10, "IMPORTANT": 12, "INTERESTING": 10}[tier]
        L += [f"## {icon} {tier}"] + ([_news_line(n) for n in items[:cap]] or ["- Nothing in this tier."]) + [""]
    ignored = [n for n in news if n["tier"] == "IGNORE FOR NOW"]
    if ignored:
        L += [f"_⚪ IGNORE FOR NOW: {len(ignored)} lower-priority stories in the archive._", ""]

    r = p["risk_appetite"]
    L += [f"## Cross-asset risk appetite: **{r['label']}** ({r['risk_on']} risk-on vs {r['risk_off']} risk-off signals)",
          "| Signal | Value | Reading | Rule |", "|---|---|---|---|"]
    L += [f"| {s['Signal']} | {s['Value']} | {s['Reading']} | {s['Rule']} |" for s in r["signals"]]
    L += ["", f"_{r['methodology']}_", ""]

    m = p["markets"]
    L += ["## Markets"]
    for key, title in (("us_indices", "US indices"), ("volatility", "Volatility"), ("india", "India"),
                       ("europe", "Europe"), ("asia_pacific", "Asia-Pacific"), ("us_yields", "US Treasury yields (%)"),
                       ("currencies", "Currencies"), ("precious_metals", "Precious metals"),
                       ("energy_industrial", "Energy & industrial commodities"), ("crypto", "Crypto")):
        L += _table(m.get(key, []), title)
    for key, title in (("us_sectors_by_1w", "US sectors"), ("us_themes_by_1w", "US themes"),
                       ("india_sectors_by_1w", "Indian sectors")):
        rows = m.get(key) or []
        if rows:
            lead = ", ".join(f"{x['Name']} {_pct(x['1W %'])}" for x in rows[:3])
            lag = ", ".join(f"{x['Name']} {_pct(x['1W %'])}" for x in rows[-3:])
            L += [f"- **{title} — 1W leaders:** {lead} · **laggards:** {lag}"]
    L += [""]

    gd = p["gold"]
    L += ["## Gold"]
    if gd.get("gold"):
        g = gd["gold"]
        L += [f"- COMEX gold {_num(g['Last'])} USD/oz · 1D {_pct(g['1D %'])} · 1W {_pct(g['1W %'])} · 1M {_pct(g['1M %'])} · "
              f"YTD {_pct(g['YTD %'])} (bar {g['Last bar']}, {g['Freshness']})"]
    if gd.get("gold_inr_per_10g", {}).get("value"):
        L += [f"- ≈ ₹{gd['gold_inr_per_10g']['value']:,.0f} per 10 g — {gd['gold_inr_per_10g']['basis']}"]
    for k, lab in (("reading_1m", "1-month driver check"), ("reading_1y", "1-year driver check")):
        if gd.get(k):
            L += [f"- **{lab} (rule-based):** {gd[k]}"]
    if gd.get("cftc_gold"):
        c = gd["cftc_gold"]
        L += [f"- CFTC managed money net long {c['mm_net']:,} contracts ({c['net_pct_open_interest']}% of OI), "
              f"week change {c['weekly_change']:+,}, {c['percentile_in_window']:.0f}th percentile of {c['weeks_in_window']} weeks "
              f"→ {c['reading']} (as of {c['as_of']})"]
    L += [""]

    geo = p.get("geopolitics") or []
    if geo:
        L += ["## Geopolitics — most active theaters (7 days)"]
        for t in geo:
            L += [f"**{t['theater']}** — {t['stories_7d']} stories · trend: {t['trend']}"]
            L += [f"- [{e['tier']}] [{e['headline']}]({e['url']}) — {e['source']}, {e['when_utc']} UTC · {e['confirmed']}"
                  for e in t["top_events"]]
        L += ["_Theater matching is keyword-based; see the Geopolitics page for the framework and full event cards._", ""]
    cbs = p.get("central_banks") or []
    if cbs:
        L += ["## Central banks"]
        for cb in cbs:
            rate = (f"{cb['rate_label']} {cb['rate']}% (as of {cb['rate_as_of']}, last change {cb['last_change']})"
                    if cb.get("rate") is not None else cb["rate_label"])
            comms = [c for c in cb.get("latest_communications", []) if not c["routine"]][:1]
            last = f" · latest: [{comms[0]['headline']}]({comms[0]['url']}) ({comms[0]['published_utc']})" if comms else ""
            L += [f"- **{cb['bank']}**: {rate}{last}"]
        L += [""]
    cal = [e for e in (p.get("economic_calendar") or []) if e.get("importance") in ("high", "medium")]
    if cal:
        L += ["## Economic calendar (IST) — actuals only when officially released; no forecasts"]
        for e in cal[:14]:
            rd = "; ".join(f"{x['indicator']}: " + (f"actual {x['actual']} (prev {x['previous']})" if x.get("actual")
                                                    else f"prev {x.get('previous', '—')} [{x.get('status', '')}]")
                           for x in e.get("readings", []) if "indicator" in x)
            L += [f"- {e['date']} {e.get('time_ist', '')} · **{e['event']}** ({e['importance']})" + (f" — {rd}" if rd else "")]
        L += [""]
    tr = p.get("trends_radar") or []
    if tr:
        L += ["## Trends radar (rule-based stage, price + news evidence)"]
        for stage in ("Gaining momentum", "Emerging", "Established", "Crowded", "Weakening"):
            names = [f"{r['Theme']} ({r['RS 3M (pp)']:+.1f}pp 3M RS)" for r in tr if r["Stage"] == stage and r.get("RS 3M (pp)") is not None]
            if names:
                L += [f"- **{stage}:** " + ", ".join(names)]
        L += [""]

    L += ["## Upcoming events (IST)"]
    ev = p["upcoming_events"]
    L += [f"- {e['date']} · {e.get('time_ist') or ''} · {e['event']} ({e['importance']}) — [source]({e['source']})"
          if str(e.get("source", "")).startswith("http") else f"- {e['date']} · {e['event']} ({e['importance']})"
          for e in ev[:15]] or ["- No scheduled events found."]
    earn = p["upcoming_earnings_watchlist"]
    if earn:
        L += ["", "**Earnings (tracked large caps, next 7 days):** " +
              ", ".join(f"{e['symbol']} {e['date']}{' ' + e['when'] if e.get('when') else ''}" for e in earn[:25])]
    L += ["", "## Data quality"]
    dq = p["data_quality"]
    L += ["- Freshness: " + ", ".join(f"{k}: {v}" for k, v in dq["freshness_counts"].items())]
    if dq["missing_symbols"]:
        L += [f"- Missing: {', '.join(dq['missing_symbols'])}"]
    L += [f"- Error: {e}" for e in dq["errors"]]
    L += [f"- {dq['x_twitter']}", "- Not covered (no authorised free source): " +
          "; ".join(f"[{x['item']}]({x['official_link']})" for x in dq["not_available_in_this_app"])]
    return "\n".join(L)


# ----------------------------------------------------------------------------- generate / archive
def generate(edition: str, use_ai: bool = True, refresh: bool = True, force_data: bool = False,
             now: datetime | None = None) -> Briefing:
    from tradingos.config import load_config
    ed = EDITIONS[edition]
    now = now or datetime.now(timezone.utc)
    if refresh:
        try:
            from tradingos.data.news import refresh_news
            # Keep 35 days so geopolitics/trends attention baselines (7d vs prior 28d) can form; pages and briefings
            # still filter by publication date, so older items are never presented as new.
            st = refresh_news([], max_age_days=35)
            log.info("news refresh: %s stored, %s errors", st["stored"], len(st["errors"]))
        except Exception as e:
            log.warning("news refresh failed: %s", e)
    payload = build_payload(edition, force=force_data, now=now)
    det = deterministic_markdown(payload)
    ai_md, model, err = "", "", ""
    if use_ai and load_config().ai_configured:
        from tradingos.ai import gemini
        try:
            ai_md = gemini.intel_analysis("daily_briefing", ai_payload(payload), subject=edition, edition_title=ed.title,
                                          edition_date=payload["edition"]["generated_at_ist"][:15],
                                          edition_time=payload["edition"]["generated_at_ist"], edition_focus=ed.focus)
            model = gemini.get_client().active_model
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    elif use_ai:
        err = "AI not configured (GROQ_API_KEY or GEMINI_API_KEY)."
    from tradingos.ai.gemini import to_jsonable
    b = Briefing(edition=edition, edition_date=edition_date_for(ed, now), deterministic_md=det, ai_md=ai_md,
                 model=model, ai_error=err, payload_json=json.dumps(to_jsonable(payload), default=str)[:1_500_000])
    with session_scope() as s:
        s.add(b)
    return b


def latest(edition: str | None = None, edition_date: date | None = None) -> Briefing | None:
    with session_scope() as s:
        q = select(Briefing)
        if edition:
            q = q.where(Briefing.edition == edition)
        if edition_date:
            q = q.where(Briefing.edition_date == edition_date)
        return s.scalars(q.order_by(Briefing.created_at.desc()).limit(1)).first()


def archive(limit: int = 60, edition: str | None = None) -> list[Briefing]:
    with session_scope() as s:
        q = select(Briefing)
        if edition:
            q = q.where(Briefing.edition == edition)
        return list(s.scalars(q.order_by(Briefing.created_at.desc()).limit(limit)).all())


def get(briefing_id: int) -> Briefing | None:
    with session_scope() as s:
        return s.get(Briefing, briefing_id)


def default_edition(now: datetime | None = None) -> str:
    """The edition most relevant right now (the latest one whose scheduled time has passed today)."""
    now = now or datetime.now(timezone.utc)
    best, best_at = "global_morning", None
    for ed in EDITIONS.values():
        if ed.key in ("weekly_review", "monthly_review"):
            continue
        d = now.astimezone(ed.tz).date()
        if not runs_on(ed, d):
            continue
        at = scheduled_at(ed, d)
        if at <= now and (best_at is None or at > best_at):
            best, best_at = ed.key, at
    return best
