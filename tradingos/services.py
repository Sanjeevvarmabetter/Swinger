"""Orchestration layer: assembles structured, timestamped context for UI, scripts and Gemini."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select

from tradingos.analysis import indicators as ind
from tradingos.analysis.market import index_overview, market_regime, sector_performance, universe_breadth
from tradingos.analysis.technical import analyze, suggest_levels
from tradingos.data.base import market_status
from tradingos.data.macro import macro_snapshot, recession_signals
from tradingos.data.news import query_news
from tradingos.data.providers import SECTOR_ETFS, get_market_provider, load_universe
from tradingos.db.models import EconEvent, TradePlan
from tradingos.db.session import session_scope
from tradingos.journal.service import account_state, sizing_equity
from tradingos.risk.engine import context_checks, evaluate_trade
from tradingos.settings import TradingSettings

INFO_FIELDS = ["shortName", "longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE",
               "priceToSalesTrailing12Months", "revenueGrowth", "earningsGrowth", "grossMargins",
               "operatingMargins", "profitMargins", "freeCashflow", "operatingCashflow", "totalDebt", "totalCash",
               "debtToEquity", "beta", "shortPercentOfFloat", "targetMeanPrice", "targetLowPrice",
               "targetHighPrice", "recommendationKey", "numberOfAnalystOpinions", "fiftyTwoWeekHigh",
               "fiftyTwoWeekLow"]


def ticker_meta(ticker: str) -> dict:
    uni = load_universe().set_index("ticker")
    if ticker in uni.index:
        r = uni.loc[ticker]
        return {"name": r["name"], "sector": r["sector"], "themes": r["themes"], "type": r["type"]}
    return {"name": ticker, "sector": "", "themes": "", "type": "Stock"}


def latest_prices(tickers: list[str]) -> tuple[dict[str, float], dict]:
    if not tickers:
        return {}, {}
    res = get_market_provider().history(tickers, period="5d")
    if not res.ok:
        return {}, res.meta()
    return {t: float(df["Close"].iloc[-1]) for t, df in res.data.items()}, res.meta()


def fundamentals(ticker: str) -> dict:
    """Fundamental snapshot + quarterly trends, all computed in Python from provider data."""
    prov = get_market_provider()
    info = prov.info(ticker)
    fin = prov.financials(ticker)
    earn = prov.earnings(ticker)
    out: dict = {"source": prov.name, "info": {}, "quarters": [], "earnings_history": [], "next_earnings": None,
                 "errors": [r.error for r in (info, fin, earn) if r.error]}
    if info.ok:
        out["info"] = {k: info.data.get(k) for k in INFO_FIELDS if info.data.get(k) is not None}
    if fin.ok and "income_q" in fin.data:
        inc = fin.data["income_q"]
        cf = fin.data.get("cashflow_q")
        cols = sorted(inc.columns)[-6:]
        for c in cols:
            def g(df, row, col=c):
                try:
                    v = df.loc[row, col]
                    return None if pd.isna(v) else float(v)
                except (KeyError, TypeError):
                    return None
            rev, gp, op, eps = (g(inc, "Total Revenue"), g(inc, "Gross Profit"), g(inc, "Operating Income"),
                                g(inc, "Diluted EPS"))
            q = {"quarter_end": pd.Timestamp(c).date().isoformat(), "revenue": rev, "diluted_eps": eps,
                 "gross_margin_pct": gp / rev * 100 if rev and gp is not None else None,
                 "operating_margin_pct": op / rev * 100 if rev and op is not None else None,
                 "free_cash_flow": g(cf, "Free Cash Flow") if cf is not None else None}
            out["quarters"].append(q)
        qs = out["quarters"]
        for i, q in enumerate(qs):
            prev_y = qs[i - 4] if i >= 4 else None
            q["revenue_yoy_pct"] = ((q["revenue"] / prev_y["revenue"] - 1) * 100
                                    if prev_y and prev_y["revenue"] and q["revenue"] else None)
    if earn.ok:
        out["next_earnings"] = earn.data.get("next_date")
        h = earn.data.get("history")
        if isinstance(h, pd.DataFrame):
            past = h[h["Reported EPS"].notna()].head(6) if "Reported EPS" in h else h.head(6)
            out["earnings_history"] = [{"date": i.date().isoformat(), **{k: (None if pd.isna(v) else float(v))
                                                                         for k, v in r.items()}}
                                       for i, r in past.iterrows()]
    return out


def stock_context(ticker: str, cfg: TradingSettings, with_fundamentals: bool = True, force: bool = False) -> dict:
    ticker = ticker.strip().upper()
    meta = ticker_meta(ticker)
    sec_etf = SECTOR_ETFS.get(meta["sector"])
    syms = [ticker, "SPY"] + ([sec_etf] if sec_etf else [])
    res = get_market_provider().history(syms, period="5y", force=force)  # 5y so weekly 200-period MA exists
    if not res.ok or ticker not in (res.data or {}):
        return {"ticker": ticker, "error": f"No price data for {ticker}. {res.error or ''}".strip(),
                "data_meta": res.meta()}
    full, spy_full = res.data[ticker], res.data.get("SPY")
    df, spy = full.tail(504), (spy_full.tail(504) if spy_full is not None else None)
    daily = analyze(df, spy, cfg.breakout_lookback, cfg.rs_lookback_days, rel_vol_confirm=cfg.rel_volume_breakout)
    weekly = analyze(ind.to_weekly(full), ind.to_weekly(spy_full) if spy_full is not None else None, breakout_lookback=26,
                     rs_lookback=13, pivot_k=3)
    ctx = {"ticker": ticker, **meta, "data_meta": res.meta(), "market_status_now": market_status(),
           "daily": daily, "weekly": weekly, "df": df}
    if sec_etf and sec_etf in res.data and spy is not None:
        ctx["sector_etf"] = {"etf": sec_etf, "rs_vs_spy_3m_pp": ind.relative_strength(
            res.data[sec_etf]["Close"], spy["Close"], 63), "return_1m_pct": ind.pct_return(res.data[sec_etf]["Close"], 21)}
    news = query_news(days=14, ticker=ticker)
    if news.empty:
        yn = get_market_provider().news(ticker)
        if yn.ok:
            news = pd.DataFrame([{"published_utc": n["published_at"], "headline": n["headline"], "source": n["source"],
                                  "url": n["url"]} for n in yn.data])
    ctx["news"] = news.head(12).to_dict("records") if len(news) else []
    if with_fundamentals:
        ctx["fundamentals"] = fundamentals(ticker)
        ne = ctx["fundamentals"].get("next_earnings")
        ctx["days_to_earnings"] = (ne - date.today()).days if ne else None
    return ctx


def ai_payload_from_context(ctx: dict) -> dict:
    """Strip DataFrames; keep only structured, timestamped facts for Gemini."""
    return {k: v for k, v in ctx.items() if k != "df"}


def build_trade_plan(ticker: str, setup: str, cfg: TradingSettings, overrides: dict | None = None,
                     ctx: dict | None = None, regime_label: str | None = None) -> dict:
    ctx = ctx or stock_context(ticker, cfg)
    if "error" in ctx:
        return {"error": ctx["error"]}
    lv = suggest_levels(ctx["daily"], setup)
    if "error" in lv:
        return {"error": lv["error"]}
    o = overrides or {}
    entry = float(o.get("entry") if o.get("entry") is not None else lv["entry"])
    stop = float(o.get("stop") if o.get("stop") is not None else lv["stop"])
    t1 = float(o.get("target1")) if o.get("target1") is not None else (float(lv["target1"]) if lv.get("target1") is not None else None)
    t2 = float(o.get("target2")) if o.get("target2") is not None else (float(lv["target2"]) if lv.get("target2") is not None else None)
    state = account_state(cfg, latest_prices([p.ticker for p in account_state(cfg)["open_positions"]])[0])
    equity = sizing_equity(state)
    extra = context_checks(ctx["daily"], ctx.get("days_to_earnings"), regime_label)
    ev = evaluate_trade(ctx["ticker"], entry, stop, t1, t2, equity, max(0.0, state["cash"]),
                        state["open_positions"], cfg, extra)
    return {"ticker": ctx["ticker"], "setup": setup, "levels": lv, "entry": entry, "stop": stop, "target1": t1,
            "target2": t2, "overridden": bool(o), "evaluation": ev, "equity": equity, "account": state,
            "context": ctx, "data_as_of": ctx["daily"].get("as_of")}


def save_trade_plan(plan: dict, thesis: str, catalyst: str, risks: str, holding_period: str,
                    ai_review: str = "") -> int:
    ev = plan["evaluation"]
    with session_scope() as s:
        p = TradePlan(ticker=plan["ticker"], setup=plan["setup"], thesis=thesis,
                      entry_trigger=plan["levels"]["entry_trigger"], entry=plan["entry"], stop=plan["stop"],
                      target1=plan["target1"], target2=plan["target2"], shares=ev.size.shares,
                      risk_usd=ev.planned_loss_net, reward_risk=ev.rr_t1, holding_period=holding_period,
                      catalyst=catalyst, risks=risks, verdict=ev.verdict,
                      checks_json=json.dumps([asdict(c) for c in ev.checks]), data_as_of=str(plan["data_as_of"]),
                      ai_review=ai_review)
        s.add(p)
        s.flush()
        return p.id


def list_plans(status: str | None = "ACTIVE") -> pd.DataFrame:
    with session_scope() as s:
        q = select(TradePlan)
        if status:
            q = q.where(TradePlan.status == status)
        rows = s.scalars(q.order_by(TradePlan.created_at.desc())).all()
        return pd.DataFrame([{"id": r.id, "created": r.created_at, "ticker": r.ticker, "setup": r.setup,
                              "verdict": r.verdict, "entry": r.entry, "stop": r.stop, "target1": r.target1,
                              "target2": r.target2, "shares": r.shares, "risk_usd": r.risk_usd,
                              "R:R": r.reward_risk, "data_as_of": r.data_as_of, "thesis": r.thesis,
                              "entry_trigger": r.entry_trigger, "status": r.status} for r in rows])


def set_plan_status(plan_id: int, status: str) -> None:
    with session_scope() as s:
        p = s.get(TradePlan, plan_id)
        if p:
            p.status = status


def upcoming_events(days: int = 21) -> pd.DataFrame:
    today = date.today()
    with session_scope() as s:
        rows = s.scalars(select(EconEvent).where(EconEvent.event_date >= today,
                                                 EconEvent.event_date <= today + timedelta(days=days))
                         .order_by(EconEvent.event_date)).all()
        return pd.DataFrame([{"date": r.event_date, "event": r.title, "category": r.category,
                              "importance": r.importance, "source": r.source_url, "notes": r.notes, "id": r.id}
                             for r in rows])


def market_context(cfg: TradingSettings, force: bool = False, include_macro: bool = True) -> dict:
    idx, idx_res = index_overview(force)
    sectors, sec_res = sector_performance(force)
    uni = load_universe(cfg.extra_tickers)
    uni_res = get_market_provider().history(list(uni["ticker"]), period="1y", force=force)
    breadth = universe_breadth(uni_res.data) if uni_res.ok else {"stocks": 0}
    spy = (idx_res.data or {}).get("SPY") if idx_res.ok else None
    regime = market_regime(idx, spy, breadth)
    ctx = {"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "market_status_now": market_status(), "indices": idx, "index_data_meta": idx_res.meta(),
           "sectors": sectors, "sector_data_meta": sec_res.meta(), "breadth": breadth, "regime": regime}
    if len(idx) and spy is not None:
        rv = ind.relative_volume(spy["Volume"]).iloc[-1]
        ctx["spy_volume_trend"] = {"rel_volume_today": None if pd.isna(rv) else round(float(rv), 2),
                                   "avg_vol_20d_vs_50d": round(float(spy["Volume"].tail(20).mean() /
                                                                     spy["Volume"].tail(50).mean()), 2)}
    if include_macro:
        macro, errs = macro_snapshot(force)
        ctx["macro"], ctx["macro_errors"] = macro, errs
        ctx["recession_signals"] = recession_signals(macro)
    news = query_news(days=3)
    ctx["news_macro_geo"] = news[news["category"].isin(["macro", "geopolitics"])].head(25) if len(news) else news
    ctx["news_markets"] = news[~news["category"].isin(["macro", "geopolitics"])].head(25) if len(news) else news
    ctx["upcoming_events"] = upcoming_events()
    return ctx
