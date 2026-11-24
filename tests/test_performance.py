from datetime import datetime

import pandas as pd
import pytest

from tradingos.journal import service as js
from tradingos.performance import metrics as pm
from tradingos.performance.backtest import BTParams, run_backtest
from tradingos.settings import TradingSettings

CFG = TradingSettings()


def _trade(ticker, entry, stop, exit_, d0, d1, qty=3, setup="Breakout"):
    tid = js.open_trade(ticker=ticker, setup=setup, entry_thesis="t", planned_entry=entry, initial_stop=stop,
                        target1=entry * 1.15, target2=None, fill_price=entry, qty=qty, filled_at=d0, cfg=CFG,
                        equity=300)
    js.record_exit(tid, qty=qty, price=exit_, filled_at=d1)
    return tid


def test_core_metrics_and_drawdown():
    _trade("A", 20, 19, 23, datetime(2026, 1, 5), datetime(2026, 1, 15))    # +9
    _trade("B", 20, 19, 19, datetime(2026, 1, 16), datetime(2026, 1, 20))   # -3
    _trade("C", 20, 19, 19, datetime(2026, 1, 21), datetime(2026, 1, 25))   # -3
    _trade("D", 20, 19, 22, datetime(2026, 2, 2), datetime(2026, 2, 10), setup="Pullback")  # +6
    closed = js.trades_dataframe("CLOSED")
    m = pm.core_metrics(closed)
    assert m["trades"] == 4 and m["win_rate_pct"] == 50.0
    assert m["profit_factor"] == pytest.approx(15 / 6)
    assert m["expectancy_usd"] == pytest.approx(9 / 4)
    assert m["avg_r"] == pytest.approx((3 - 1 - 1 + 2) / 4)
    curve = pm.equity_curve(closed, js.capital_flows_dataframe(), 300)
    dd = pm.max_drawdown(curve)
    assert dd["max_drawdown_usd"] == pytest.approx(-6)
    assert dd["max_drawdown_pct"] == pytest.approx(-6 / 309 * 100, abs=0.01)
    mr = pm.monthly_returns(closed, curve)
    assert list(mr["month"]) == ["2026-01", "2026-02"]
    assert mr.iloc[0]["pnl_usd"] == pytest.approx(3)
    by = pm.breakdown(closed, "setup")
    assert set(by["setup"]) == {"Breakout", "Pullback"}


def test_sample_warning():
    assert pm.sample_warning(3, CFG) is not None
    assert pm.sample_warning(50, CFG) is None


def test_diagnostics_flags():
    tid = js.open_trade(ticker="X", setup="Breakout", entry_thesis="t", planned_entry=20, initial_stop=15,
                        target1=30, target2=None, fill_price=20.5, qty=3, filled_at=datetime(2026, 3, 2), cfg=CFG,
                        equity=300)  # risk $16.5 vs allowed $3; fill 2.5% above plan
    js.change_stop(tid, 14, "room")
    js.record_exit(tid, qty=3, price=21, filled_at=datetime(2026, 3, 5))  # small win before target
    d = pm.diagnostics(js.trades_dataframe(), CFG)
    assert d["risk_violations"] and d["stop_widened"] and d["poor_entries"] and d["possible_early_exits"]


def test_empty_inputs():
    assert pm.core_metrics(pd.DataFrame()) == {"trades": 0}
    assert pm.diagnostics(pd.DataFrame(), CFG)["risk_violations"] == []


def test_backtest_runs_and_is_conservative(uptrend):
    trades, stats = run_backtest(uptrend, BTParams(rule="momentum"))
    if stats["trades"]:
        assert (trades["entry_date"] > trades["signal_date"]).all()  # no same-bar lookahead
        assert set(trades["reason"]) <= {"stop", "target", "time"}
