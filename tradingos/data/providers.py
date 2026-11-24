"""Market-data provider abstraction + yfinance implementation.

To add Polygon / FMP / Finnhub later: implement MarketDataProvider and register it in
get_market_provider(). Nothing else in the app needs to change.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from tradingos.config import PROJECT_ROOT, load_config
from tradingos.data import cache
from tradingos.data.base import DataResult, Freshness, classify_bar_freshness

log = logging.getLogger(__name__)

OHLCV = ["Open", "High", "Low", "Close", "Volume"]

INDEX_SYMBOLS = {
    "S&P 500": "^GSPC",
    "Nasdaq Composite": "^IXIC",
    "Nasdaq 100": "^NDX",
    "Russell 2000": "^RUT",
    "Dow Jones": "^DJI",
}
INDICATOR_SYMBOLS = {
    "VIX": "^VIX",
    "US 10Y Yield (%)": "^TNX",
    "US Dollar Index": "DX-Y.NYB",
    "Gold (GLD)": "GLD",
}
OVERVIEW_SYMBOLS = {
    "S&P 500 (SPY)": "SPY",
    "Nasdaq 100 (QQQ)": "QQQ",
    "Russell 2000 (IWM)": "IWM",
    "Dow Jones (DIA)": "DIA",
    "Volatility (VIX)": "^VIX",
    "Gold (GLD)": "GLD",
    "US 10Y Yield": "^TNX",
    "US Dollar (DXY)": "DX-Y.NYB",
}
SECTOR_ETFS = {
    "Technology": "XLK", "Communication Services": "XLC", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Energy": "XLE", "Financials": "XLF", "Health Care": "XLV",
    "Industrials": "XLI", "Materials": "XLB", "Real Estate": "XLRE", "Utilities": "XLU",
}


def load_universe(extra: list[str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(PROJECT_ROOT / "config" / "universe.csv", dtype=str).fillna("")
    df["ticker"] = df["ticker"].str.strip().str.upper()
    if extra:
        new = [t.strip().upper() for t in extra if t.strip() and t.strip().upper() not in set(df["ticker"])]
        if new:
            df = pd.concat([df, pd.DataFrame({"ticker": new, "name": new, "sector": "Unknown",
                                              "themes": "", "type": "Stock"})], ignore_index=True)
    return df.drop_duplicates("ticker").reset_index(drop=True)


def _last_bar_date(frames: dict[str, pd.DataFrame]) -> date | None:
    """Representative as-of date for a batch: the most common last-bar date (ties → older)."""
    dates = [df.index[-1].date() for df in frames.values() if df is not None and len(df)]
    if not dates:
        return None
    counts = pd.Series(dates).value_counts()
    top = counts[counts == counts.max()].index
    return min(top)


def _lagging(frames: dict[str, pd.DataFrame], as_of: date | None) -> list[str]:
    """Tickers whose last bar is older than the batch as-of date (halted, delisted or stale feed)."""
    if as_of is None:
        return []
    return [f"{t} (last bar {df.index[-1].date()})" for t, df in frames.items() if df.index[-1].date() < as_of]


class MarketDataProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def history(self, tickers: list[str], period: str = "1y", interval: str = "1d",
                force: bool = False) -> DataResult[dict[str, pd.DataFrame]]: ...

    @abstractmethod
    def info(self, ticker: str) -> DataResult[dict]: ...

    @abstractmethod
    def earnings(self, ticker: str) -> DataResult[dict]: ...

    @abstractmethod
    def news(self, ticker: str) -> DataResult[list[dict]]: ...

    @abstractmethod
    def financials(self, ticker: str) -> DataResult[dict[str, pd.DataFrame]]: ...


class YFinanceProvider(MarketDataProvider):
    """Yahoo Finance via yfinance. Unofficial, delayed, best-effort — prototype use only."""

    name = "Yahoo Finance (yfinance, delayed/EOD — unofficial)"

    def __init__(self, history_ttl: int = 15 * 60, info_ttl: int = 12 * 3600):
        self.history_ttl = history_ttl
        self.info_ttl = info_ttl

    # ------------------------------------------------------------------ prices
    def history(self, tickers, period="1y", interval="1d", force=False):
        import yfinance as yf

        tickers = sorted({t.strip().upper() for t in tickers if t and t.strip()})
        if not tickers:
            return DataResult(None, self.name, error="No tickers requested")
        key = f"hist|{period}|{interval}|{','.join(tickers)}"

        def fetch():
            raw = yf.download(tickers, period=period, interval=interval, group_by="ticker",
                              auto_adjust=True, progress=False, threads=True)
            return raw if raw is not None and len(raw) else None

        try:
            raw = cache.cached(key, self.history_ttl, fetch, force=force)
        except Exception as e:  # network, rate-limit, parsing
            log.warning("yfinance download failed: %s", e)
            return DataResult(None, self.name, error=f"Download failed: {e}", missing=tickers)
        if raw is None:
            return DataResult(None, self.name, error="Provider returned no data", missing=tickers)

        frames, missing = {}, []
        for t in tickers:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df[[c for c in OHLCV if c in df.columns]].dropna(subset=["Close"])
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                if len(df) == 0:
                    missing.append(t)
                else:
                    frames[t] = df.astype(float)
            except KeyError:
                missing.append(t)
        last = _last_bar_date(frames)
        fresh = classify_bar_freshness(last) if interval == "1d" else (
            Freshness.CURRENT if last else Freshness.MISSING)
        missing += _lagging(frames, last)
        return DataResult(frames or None, self.name, as_of=last, freshness=fresh, missing=missing,
                          error=None if frames else "No usable price series",
                          notes="Daily bars, split/dividend adjusted. Not real-time.")

    # ------------------------------------------------------------------ fundamentals
    def info(self, ticker):
        import yfinance as yf

        t = ticker.upper()
        try:
            data = cache.cached(f"info|{t}", self.info_ttl, lambda: yf.Ticker(t).info or None)
        except Exception as e:
            return DataResult(None, self.name, error=f"info failed: {e}")
        if not data:
            return DataResult(None, self.name, error="No company info returned")
        return DataResult(data, self.name, as_of=datetime.now(timezone.utc).date(),
                          freshness=Freshness.STATIC, notes="Snapshot fields from Yahoo; may lag filings.")

    def financials(self, ticker):
        import yfinance as yf

        t = ticker.upper()

        def fetch():
            tk = yf.Ticker(t)
            out = {}
            for name, attr in (("income_q", "quarterly_income_stmt"), ("cashflow_q", "quarterly_cashflow"),
                               ("balance_q", "quarterly_balance_sheet")):
                try:
                    df = getattr(tk, attr)
                    if df is not None and len(df):
                        out[name] = df
                except Exception:
                    pass
            return out or None

        try:
            data = cache.cached(f"fin|{t}", self.info_ttl, fetch)
        except Exception as e:
            return DataResult(None, self.name, error=f"financials failed: {e}")
        if not data:
            return DataResult(None, self.name, error="No financial statements returned")
        cols = [c for df in data.values() for c in df.columns]
        as_of = max(pd.Timestamp(c) for c in cols).date() if cols else None
        return DataResult(data, self.name, as_of=as_of, freshness=Freshness.STATIC,
                          notes="Quarterly statements as reported to Yahoo; verify against SEC filings.")

    def earnings(self, ticker):
        import yfinance as yf

        t = ticker.upper()

        def fetch():
            tk = yf.Ticker(t)
            out: dict = {}
            try:
                cal = tk.calendar or {}
                out["calendar"] = cal
            except Exception:
                out["calendar"] = {}
            try:
                ed = tk.get_earnings_dates(limit=8)
                if ed is not None and len(ed):
                    ed = ed.copy()
                    ed.index = ed.index.tz_localize(None) if ed.index.tz is not None else ed.index
                    out["history"] = ed
            except Exception:
                pass
            return out

        try:
            data = cache.cached(f"earn|{t}", self.info_ttl, fetch)
        except Exception as e:
            return DataResult(None, self.name, error=f"earnings failed: {e}")

        cfg = load_config()
        if cfg.finnhub_api_key:
            fh = fetch_finnhub_earnings(t, cfg.finnhub_api_key)
            if fh and fh.get("next_date"):
                data["next_date"] = fh["next_date"]
                data["consensus"] = fh
                return DataResult(data, "Finnhub Official Calendar", as_of=datetime.now(timezone.utc).date(),
                                  freshness=Freshness.CURRENT,
                                  notes="Official earnings calendar from Finnhub API.")

        next_date = next_earnings_date(data)
        data["next_date"] = next_date
        return DataResult(data, self.name, as_of=datetime.now(timezone.utc).date(),
                          freshness=Freshness.STATIC,
                          missing=[] if next_date else ["next earnings date"],
                          notes="Earnings dates from Yahoo can be estimates; confirm on the company IR site.")

    def news(self, ticker):
        t = ticker.upper()
        cfg = load_config()
        if cfg.finnhub_api_key:
            fh_items = fetch_finnhub_news(t, cfg.finnhub_api_key)
            if fh_items:
                return DataResult(fh_items, "Finnhub News Feed", freshness=Freshness.CURRENT)

        import yfinance as yf
        try:
            raw = cache.cached(f"news|{t}", 30 * 60, lambda: yf.Ticker(t).news or [])
        except Exception as e:
            return DataResult(None, self.name, error=f"news failed: {e}")
        items = [normalize_yahoo_news(n, t) for n in raw]
        items = [i for i in items if i]
        return DataResult(items, "Yahoo Finance news feed", freshness=Freshness.CURRENT if items else Freshness.MISSING)


def next_earnings_date(earn: dict | None, today: date | None = None) -> date | None:
    if not earn:
        return None
    today = today or datetime.now(timezone.utc).date()
    cands: list[date] = []
    cal = earn.get("calendar") or {}
    for d in cal.get("Earnings Date", []) or []:
        try:
            cands.append(pd.Timestamp(d).date())
        except Exception:
            pass
    hist = earn.get("history")
    if isinstance(hist, pd.DataFrame) and len(hist):
        cands.extend(pd.Timestamp(i).date() for i in hist.index)
    future = sorted(d for d in cands if d >= today)
    return future[0] if future else None


def normalize_yahoo_news(n: dict, ticker: str = "") -> dict | None:
    c = n.get("content", n)
    title = c.get("title")
    if not title:
        return None
    url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
           or c.get("link") or "")
    pub = c.get("pubDate") or c.get("displayTime")
    if not pub and n.get("providerPublishTime"):
        pub = datetime.fromtimestamp(n["providerPublishTime"], tz=timezone.utc).isoformat()
    provider = (c.get("provider") or {}).get("displayName") or n.get("publisher") or "Yahoo Finance"
    tickers = [s.get("symbol") for s in ((c.get("finance") or {}).get("stockTickers") or []) if s.get("symbol")]
    if ticker and ticker not in tickers:
        tickers.append(ticker)
    return {
        "headline": title.strip(),
        "summary": (c.get("summary") or c.get("description") or "").strip(),
        "source": f"{provider} (via Yahoo Finance)",
        "url": url,
        "published_at": pd.Timestamp(pub).tz_convert("UTC").tz_localize(None).to_pydatetime() if pub else None,
        "tickers": tickers,
    }


def fetch_finnhub_earnings(ticker: str, token: str) -> dict | None:
    """Fetch confirmed upcoming earnings date and analyst estimates from Finnhub."""
    try:
        today = date.today().isoformat()
        future = (date.today() + timedelta(days=120)).isoformat()
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"symbol": ticker.upper(), "from": today, "to": future, "token": token},
            timeout=10,
        )
        if r.ok:
            events = r.json().get("earningsCalendar", [])
            if events:
                evt = events[0]
                d = pd.Timestamp(evt["date"]).date()
                return {
                    "next_date": d,
                    "eps_estimate": evt.get("epsEstimate"),
                    "revenue_estimate": evt.get("revenueEstimate"),
                    "quarter": evt.get("quarter"),
                    "year": evt.get("year"),
                }
    except Exception as e:
        log.warning("Finnhub earnings query failed for %s: %s", ticker, e)
    return None


def fetch_finnhub_news(ticker: str, token: str) -> list[dict]:
    """Fetch company news directly from Finnhub API."""
    try:
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=14)).isoformat()
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker.upper(), "from": start, "to": today, "token": token},
            timeout=10,
        )
        if r.ok and isinstance(r.json(), list):
            items = []
            for n in r.json()[:25]:
                headline = (n.get("headline") or "").strip()
                if not headline:
                    continue
                pub_ts = n.get("datetime")
                pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).replace(tzinfo=None) if pub_ts else None
                items.append({
                    "headline": headline,
                    "summary": (n.get("summary") or "").strip(),
                    "source": f"{n.get('source') or 'Finnhub'} (via Finnhub API)",
                    "url": n.get("url") or "",
                    "published_at": pub_dt,
                    "tickers": [ticker.upper()],
                })
            return items
    except Exception as e:
        log.warning("Finnhub news query failed for %s: %s", ticker, e)
    return []


def test_finnhub_connection() -> tuple[bool, str]:
    cfg = load_config()
    if not cfg.finnhub_api_key:
        return False, "FINNHUB_API_KEY is not set in .env."
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": "AAPL", "token": cfg.finnhub_api_key},
            timeout=10,
        )
        if r.ok and "c" in r.json():
            px = r.json()["c"]
            return True, f"Connected to Finnhub: AAPL real-time quote ${px:.2f}"
        return False, f"Finnhub returned HTTP {r.status_code}: {r.text[:80]}"
    except Exception as e:
        return False, f"Finnhub connection failed: {e}"


def test_fmp_connection() -> tuple[bool, str]:
    cfg = load_config()
    if not cfg.fmp_api_key:
        return False, "FMP_API_KEY is not set in .env."
    try:
        r = requests.get(
            "https://financialmodelingprep.com/stable/quote",
            params={"symbol": "AAPL", "apikey": cfg.fmp_api_key},
            timeout=10,
        )
        if r.ok and isinstance(r.json(), list) and len(r.json()) and "price" in r.json()[0]:
            px = r.json()[0]["price"]
            return True, f"Connected to FMP: AAPL real-time quote ${px:.2f}"
        return False, f"FMP returned HTTP {r.status_code}: {r.text[:80]}"
    except Exception as e:
        return False, f"FMP connection failed: {e}"


def test_fred_connection() -> tuple[bool, str]:
    cfg = load_config()
    if not cfg.fred_api_key:
        return False, "FRED_API_KEY is not set in .env."
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "DGS10", "api_key": cfg.fred_api_key, "file_type": "json"},
            timeout=10,
        )
        if r.ok and "observations" in r.json():
            n = len(r.json()["observations"])
            return True, f"Connected to St. Louis Fed FRED: {n:,} observations"
        return False, f"FRED returned HTTP {r.status_code}: {r.text[:80]}"
    except Exception as e:
        return False, f"FRED connection failed: {e}"


_PROVIDER: MarketDataProvider | None = None


def get_market_provider() -> MarketDataProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = YFinanceProvider()
    return _PROVIDER


def set_market_provider(p: MarketDataProvider) -> None:
    """Swap provider (also used by tests to inject fake data)."""
    global _PROVIDER
    _PROVIDER = p


__all__ = ["MarketDataProvider", "YFinanceProvider", "get_market_provider", "set_market_provider",
           "load_universe", "INDEX_SYMBOLS", "INDICATOR_SYMBOLS", "SECTOR_ETFS", "next_earnings_date",
           "normalize_yahoo_news", "fetch_finnhub_earnings", "fetch_finnhub_news", "test_finnhub_connection",
           "test_fmp_connection", "test_fred_connection"]
