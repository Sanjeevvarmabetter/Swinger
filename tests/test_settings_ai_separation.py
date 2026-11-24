from datetime import date

import pytest

from tradingos.settings import TradingSettings, load_settings, save_settings


def test_settings_roundtrip_and_validation():
    s = load_settings()
    assert s.starting_capital_usd == 300 and s.risk_per_trade_pct == 1 and s.max_open_risk_pct == 2
    assert s.max_positions == 3
    s.starting_capital_usd = 500
    save_settings(s)
    assert load_settings().starting_capital_usd == 500
    with pytest.raises(ValueError):
        save_settings(TradingSettings(risk_per_trade_pct=3, max_open_risk_pct=2))
    with pytest.raises(ValueError):
        save_settings(TradingSettings(risk_per_trade_pct=50))


def test_gemini_not_configured_gives_clear_error():
    from tradingos.ai import gemini
    with pytest.raises(gemini.GeminiError, match="GEMINI_API_KEY"):
        gemini.market_analysis({"x": 1})
    ok, msg = gemini.test_connection()
    assert not ok and "GEMINI_API_KEY" in msg


def test_to_jsonable_scrubs_nan_and_dates():
    import numpy as np
    import pandas as pd
    from tradingos.ai.gemini import to_jsonable
    out = to_jsonable({"a": float("nan"), "b": np.float64(1.23456), "d": date(2026, 1, 1),
                       "df": pd.DataFrame({"x": [1]})})
    assert out["a"] is None and out["b"] == 1.2346 and out["d"] == "2026-01-01" and out["df"] == [{"x": 1}]


def test_longterm_holdings_never_affect_trading_equity():
    from tradingos import longterm
    from tradingos.journal.service import account_state
    cfg = TradingSettings()
    before = account_state(cfg)
    longterm.add_holding("US ETF", "VTI", "Vanguard Total", 100, 250, "USD", "manual", 300)
    longterm.add_holding("Gold", "GOLD", "Gold", 10, 6000, "INR", "manual", 7000)
    after = account_state(cfg)
    assert before["equity_at_cost"] == after["equity_at_cost"] == 300
    assert before["cash"] == after["cash"]


def test_databases_are_separate_files(isolated_data_dir):
    from tradingos.config import load_config
    from tradingos.db.session import longterm_engine, trading_engine
    trading_engine(); longterm_engine()
    cfg = load_config()
    assert cfg.trading_db_path != cfg.longterm_db_path
    assert cfg.trading_db_path.exists() and cfg.longterm_db_path.exists()


def test_backup(isolated_data_dir):
    from tradingos.db.session import backup_databases, trading_engine
    trading_engine()
    made = backup_databases()
    assert made and all(p.exists() for p in made)
