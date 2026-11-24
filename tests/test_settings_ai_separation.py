from datetime import date

import pytest

from tradingos.settings import AppSettings, load_settings, save_settings


def test_settings_roundtrip_and_validation():
    s = load_settings()
    assert s.breakout_lookback == 55 and s.news_max_age_days == 7 and s.extra_tickers == []
    s.news_max_age_days = 14
    s.extra_tickers = ["PLTR"]
    save_settings(s)
    assert load_settings().news_max_age_days == 14 and load_settings().extra_tickers == ["PLTR"]
    with pytest.raises(ValueError):
        save_settings(AppSettings(news_max_age_days=0))
    with pytest.raises(ValueError):
        save_settings(AppSettings(extra_tickers=["BAD TICKER!"]))


def test_old_trading_settings_json_still_loads():
    """Settings saved by the old trading version contain removed keys; they must be ignored, not crash."""
    import json
    from tradingos.db.models import Setting
    from tradingos.db.session import session_scope
    from tradingos.settings import SETTINGS_KEY
    with session_scope() as s:
        s.add(Setting(key=SETTINGS_KEY, value_json=json.dumps({"starting_capital_usd": 300, "risk_per_trade_pct": 1,
                                                                "news_max_age_days": 9})))
    cfg = load_settings()
    assert cfg.news_max_age_days == 9 and not hasattr(cfg, "risk_per_trade_pct")


def test_ai_not_configured_gives_clear_error():
    from tradingos.ai import gemini
    with pytest.raises(gemini.GeminiError, match="No AI provider configured"):
        gemini.news_impact({"x": 1})
    with pytest.raises(gemini.GeminiError, match="No AI provider configured"):
        list(gemini.get_client().chat_stream([], "hi"))
    ok, msg = gemini.test_connection()
    assert not ok and "GEMINI_API_KEY" in msg


def test_to_jsonable_scrubs_nan_and_dates():
    import numpy as np
    import pandas as pd
    from tradingos.ai.gemini import to_jsonable
    out = to_jsonable({"a": float("nan"), "b": np.float64(1.23456), "d": date(2026, 1, 1),
                       "df": pd.DataFrame({"x": [1]})})
    assert out["a"] is None and out["b"] == 1.2346 and out["d"] == "2026-01-01" and out["df"] == [{"x": 1}]


def test_trading_tables_are_no_longer_created(isolated_data_dir):
    from sqlalchemy import inspect
    from tradingos.db.session import trading_engine
    names = set(inspect(trading_engine()).get_table_names())
    assert {"news_items", "briefings", "ai_reports", "chat_messages", "settings"} <= names
    assert not names & {"trades", "fills", "trade_plans", "capital_flows", "watchlist", "scan_runs", "alerts"}


def test_backup(isolated_data_dir):
    from tradingos.db.session import backup_databases, trading_engine
    trading_engine()
    made = backup_databases()
    assert made and all(p.exists() for p in made)
