"""Performance analytics (Module 9). Pure functions over the journal DataFrames."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from tradingos.settings import TradingSettings


def core_metrics(closed: pd.DataFrame) -> dict:
    n = len(closed)
    if n == 0:
        return {"trades": 0}
    pnl = closed["realized_net"].astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    r = closed["r_multiple"].dropna().astype(float)
    gross_win, gross_loss = wins.sum(), -losses.sum()
    return {
        "trades": n, "wins": len(wins), "losses": len(losses), "breakeven": int((pnl == 0).sum()),
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "avg_winner": round(wins.mean(), 2) if len(wins) else None,
        "avg_loser": round(losses.mean(), 2) if len(losses) else None,
        "largest_winner": round(wins.max(), 2) if len(wins) else None,
        "largest_loser": round(losses.min(), 2) if len(losses) else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy_usd": round(pnl.mean(), 2),
        "avg_r": round(r.mean(), 2) if len(r) else None,
        "expectancy_r": round(r.mean(), 2) if len(r) else None,
        "total_realized": round(pnl.sum(), 2),
        "total_fees": round(closed["fees_total"].sum(), 2),
        "avg_holding_days": round(closed["holding_days"].dropna().mean(), 1) if closed["holding_days"].notna().any() else None,
    }


def equity_curve(closed: pd.DataFrame, flows: pd.DataFrame, starting_capital: float,
                 start: date | None = None) -> pd.DataFrame:
    """Daily curve of (a) account equity incl. capital flows and (b) performance equity excl. flows."""
    events = []
    for _, r in closed.iterrows():
        if pd.notna(r["exit_date"]):
            events.append((pd.Timestamp(r["exit_date"]).normalize(), "pnl", float(r["realized_net"])))
    for _, f in (flows.iterrows() if len(flows) else []):
        amt = f["amount_usd"] if f["kind"] == "DEPOSIT" else -f["amount_usd"]
        events.append((pd.Timestamp(f["date"]), "flow", float(amt) - float(f["fx_cost_usd"] or 0)))
    if not events:
        return pd.DataFrame()
    ev = pd.DataFrame(events, columns=["date", "type", "amount"]).sort_values("date")
    first = min(ev["date"].min(), pd.Timestamp(start)) if start else ev["date"].min()
    idx = pd.date_range(first, max(ev["date"].max(), pd.Timestamp(date.today())), freq="D")
    pnl = ev[ev["type"] == "pnl"].groupby("date")["amount"].sum().reindex(idx, fill_value=0).cumsum()
    flw = ev[ev["type"] == "flow"].groupby("date")["amount"].sum().reindex(idx, fill_value=0).cumsum()
    df = pd.DataFrame({"cum_pnl": pnl, "account_equity": starting_capital + flw + pnl,
                       "performance_equity": starting_capital + pnl}, index=idx)
    peak = df["performance_equity"].cummax()
    df["drawdown_pct"] = (df["performance_equity"] / peak - 1) * 100
    df["drawdown_usd"] = df["performance_equity"] - peak
    return df


def max_drawdown(curve: pd.DataFrame) -> dict:
    if curve.empty:
        return {"max_drawdown_pct": None, "max_drawdown_usd": None}
    i = curve["drawdown_pct"].idxmin()
    return {"max_drawdown_pct": round(float(curve["drawdown_pct"].min()), 2),
            "max_drawdown_usd": round(float(curve["drawdown_usd"].min()), 2),
            "trough_date": i.date().isoformat()}


def monthly_returns(closed: pd.DataFrame, curve: pd.DataFrame) -> pd.DataFrame:
    if closed.empty or curve.empty:
        return pd.DataFrame()
    c = closed.dropna(subset=["exit_date"]).copy()
    c["month"] = pd.to_datetime(c["exit_date"]).dt.to_period("M")
    g = c.groupby("month").agg(trades=("id", "count"), pnl=("realized_net", "sum"),
                               wins=("realized_net", lambda x: (x > 0).sum()))
    out = []
    for m, row in g.iterrows():
        start = m.start_time - timedelta(days=1)
        if start >= curve.index[0]:
            base = curve["account_equity"].asof(start)
        else:  # month starts before the curve: equity before any P&L
            base = curve["account_equity"].iloc[0] - curve["cum_pnl"].iloc[0]
        if pd.isna(base) or base <= 0:
            continue
        out.append({"month": str(m), "trades": int(row["trades"]), "wins": int(row["wins"]),
                    "pnl_usd": round(row["pnl"], 2), "return_pct": round(row["pnl"] / base * 100, 2)})
    return pd.DataFrame(out)


def breakdown(closed: pd.DataFrame, by: str) -> pd.DataFrame:
    if closed.empty:
        return pd.DataFrame()
    g = closed.groupby(closed[by].replace("", "Unspecified"))
    out = g.agg(trades=("id", "count"), pnl_usd=("realized_net", "sum"),
                win_rate_pct=("realized_net", lambda x: round((x > 0).mean() * 100, 1)),
                avg_r=("r_multiple", "mean"), avg_hold_days=("holding_days", "mean")).reset_index()
    return out.round(2).sort_values("pnl_usd", ascending=False)


def diagnostics(trades: pd.DataFrame, cfg: TradingSettings) -> dict:
    """Behavioural flags derived from recorded data. Heuristics — review each one yourself."""
    out: dict[str, list[str]] = {"risk_violations": [], "stop_widened": [], "possible_early_exits": [],
                                 "poor_entries": [], "loss_exceeded_plan": [], "overtrading_months": [],
                                 "mistake_tags": []}
    if trades.empty:
        return out
    for _, t in trades.iterrows():
        label = f"#{t['id']} {t['ticker']}"
        allowed = t["equity_at_entry"] * t["planned_risk_pct"] / 100
        if t["initial_risk_usd"] > allowed * 1.10 + 0.01:
            out["risk_violations"].append(f"{label}: initial risk ${t['initial_risk_usd']:.2f} > allowed ${allowed:.2f}")
        if t["stop_widened"]:
            out["stop_widened"].append(f"{label}: stop was moved wider after entry")
        if t["planned_entry"] and t["avg_entry"] > t["planned_entry"] * 1.01:
            out["poor_entries"].append(
                f"{label}: filled {((t['avg_entry'] / t['planned_entry']) - 1) * 100:.1f}% above planned entry")
        if t["status"] == "CLOSED" and t["r_multiple"] is not None and not pd.isna(t["r_multiple"]):
            if 0 < t["r_multiple"] < 1 and t["target"] and t["avg_exit"] and t["avg_exit"] < t["target"]:
                out["possible_early_exits"].append(f"{label}: exited at {t['r_multiple']:.2f}R before target")
            if t["r_multiple"] < -1.2:
                out["loss_exceeded_plan"].append(f"{label}: lost {t['r_multiple']:.2f}R (stop slippage/gap or late exit)")
    entries = trades.dropna(subset=["entry_date"]).copy()
    if len(entries):
        per_month = pd.to_datetime(entries["entry_date"]).dt.to_period("M").value_counts()
        for m, n in per_month.items():
            if n > cfg.max_trades_per_month:
                out["overtrading_months"].append(f"{m}: {n} entries (limit {cfg.max_trades_per_month})")
    tags = trades["mistake_tags"].fillna("").str.split(",").explode().str.strip()
    tags = tags[tags != ""]
    out["mistake_tags"] = [f"{k}: {v}×" for k, v in tags.value_counts().items()]
    return out


def sample_warning(n: int, cfg: TradingSettings) -> str | None:
    if n < cfg.min_sample_for_conclusions:
        return (f"Only {n} closed trade(s). Fewer than {cfg.min_sample_for_conclusions} trades is too small a "
                "sample to judge a strategy — treat every statistic as anecdotal.")
    return None


def period_review(trades: pd.DataFrame, start: datetime, end: datetime, cfg: TradingSettings) -> dict:
    """Structured data for a weekly/monthly review (fed to Gemini or shown directly)."""
    if trades.empty:
        return {"period": f"{start:%Y-%m-%d} → {end:%Y-%m-%d}", "opened": 0, "closed": 0}
    ed = pd.to_datetime(trades["entry_date"])
    xd = pd.to_datetime(trades["exit_date"])
    opened = trades[(ed >= start) & (ed <= end)]
    closed = trades[(trades["status"] == "CLOSED") & (xd >= start) & (xd <= end)]
    cols = ["ticker", "setup", "realized_net", "r_multiple", "holding_days", "exit_reason", "mistake_tags", "lessons"]
    return {"period": f"{start:%Y-%m-%d} → {end:%Y-%m-%d}", "opened": len(opened), "closed": len(closed),
            "metrics": core_metrics(closed), "closed_trades": closed[cols].to_dict("records"),
            "diagnostics": diagnostics(pd.concat([opened, closed]).drop_duplicates("id"), cfg),
            "sample_warning": sample_warning(len(closed), cfg)}

