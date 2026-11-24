import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets fresh, empty databases and cache — never touches real data."""
    monkeypatch.setenv("TRADINGOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    # Never let tests reach real (possibly paid) provider APIs with the developer's keys from .env.
    for k in ("FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "SEC_USER_AGENT", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "")
    from tradingos.ai import gemini
    gemini._CLIENT = None
    yield tmp_path / "data"


def make_ohlcv(closes, start="2024-01-01", vol=1_000_000, spread=0.01) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range(start, periods=len(closes))
    opens = np.r_[closes[0], closes[:-1]]
    high = np.maximum(opens, closes) * (1 + spread)
    low = np.minimum(opens, closes) * (1 - spread)
    v = np.full(len(closes), vol, dtype=float) if np.isscalar(vol) else np.asarray(vol, dtype=float)
    return pd.DataFrame({"Open": opens, "High": high, "Low": low, "Close": closes, "Volume": v}, index=idx)


@pytest.fixture
def uptrend():
    rng = np.random.default_rng(7)
    n = 300
    base = 50 * np.exp(np.cumsum(0.003 + rng.normal(0, 0.01, n)))
    return make_ohlcv(base)


@pytest.fixture
def flat():
    return make_ohlcv(np.full(300, 100.0), spread=0.005)


class FakeProvider:
    """In-memory provider used to test services/scanner without network."""
    name = "fake"

    def __init__(self, frames: dict[str, pd.DataFrame], fail: bool = False):
        self.frames, self.fail = frames, fail

    def history(self, tickers, period="1y", interval="1d", force=False):
        from tradingos.data.base import DataResult, Freshness
        if self.fail:
            return DataResult(None, self.name, error="simulated outage", missing=list(tickers))
        got = {t: self.frames[t] for t in tickers if t in self.frames}
        missing = [t for t in tickers if t not in self.frames]
        last = max((df.index[-1].date() for df in got.values()), default=None)
        return DataResult(got or None, self.name, as_of=last, freshness=Freshness.CURRENT if got else Freshness.MISSING,
                          missing=missing, error=None if got else "no data")

    def info(self, ticker):
        from tradingos.data.base import DataResult
        return DataResult(None, self.name, error="n/a")

    def financials(self, ticker):
        from tradingos.data.base import DataResult
        return DataResult(None, self.name, error="n/a")

    def earnings(self, ticker):
        from tradingos.data.base import DataResult
        return DataResult({"next_date": None}, self.name)

    def news(self, ticker):
        from tradingos.data.base import DataResult
        return DataResult([], self.name)


@pytest.fixture
def fake_provider():
    from tradingos.data import providers
    old = providers._PROVIDER

    def install(frames, fail=False):
        p = FakeProvider(frames, fail)
        providers.set_market_provider(p)
        return p
    yield install
    providers._PROVIDER = old
