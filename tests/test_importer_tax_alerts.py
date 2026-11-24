from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingos.alerts import send_alert_notification, test_notification as check_notifications
from tradingos.journal import importer, screenshots
from tradingos.journal.service import account_state, load_trades, open_trade, record_exit
from tradingos.settings import TradingSettings
from tradingos.tax.indian_tax import compute_indian_tax_report, fy_date_range, fy_for_date


def test_fy_for_date_and_range():
    # April 1, 2025 -> FY 2025-26
    assert fy_for_date(date(2025, 4, 1)) == "FY 2025-26"
    # March 31, 2026 -> FY 2025-26
    assert fy_for_date(date(2026, 3, 31)) == "FY 2025-26"
    # Jan 15, 2025 -> FY 2024-25
    assert fy_for_date(date(2025, 1, 15)) == "FY 2024-25"

    start, end = fy_date_range("FY 2025-26")
    assert start == date(2025, 4, 1)
    assert end == date(2026, 3, 31)


def test_indian_tax_report_stcg_and_ltcg():
    # Construct test closed trades dataframe
    # Trade 1: Held for 30 days (STCG)
    # Trade 2: Held for 800 days (LTCG)
    closed = pd.DataFrame([
        {
            "id": 1,
            "ticker": "AAPL",
            "qty": 10.0,
            "entry_date": "2025-05-01",
            "exit_date": "2025-05-31",
            "holding_days": 30,
            "avg_entry": 200.0,
            "avg_exit": 220.0,
            "fees_total": 5.0,
            "realized_net": 195.0,
        },
        {
            "id": 2,
            "ticker": "MSFT",
            "qty": 5.0,
            "entry_date": "2023-01-01",
            "exit_date": "2025-06-15",
            "holding_days": 896,
            "avg_entry": 250.0,
            "avg_exit": 400.0,
            "fees_total": 10.0,
            "realized_net": 740.0,
        },
    ])

    report = compute_indian_tax_report(closed, fy="FY 2025-26", fx_override=84.0, est_slab_rate_pct=30.0)
    assert report.trades_count == 2
    # Trade 1: proceeds = 10 * 220 * 84 = 184,800. cost = 10 * 200 * 84 = 168,000. fees = 5 * 84 = 420. net = 16,380
    # Trade 2: proceeds = 5 * 400 * 84 = 168,000. cost = 5 * 250 * 84 = 105,000. fees = 10 * 84 = 840. net = 62,160
    assert report.rows[0].gain_type == "STCG"
    assert report.rows[1].gain_type == "LTCG"
    assert report.rows[0].net_gain_inr == 16380.0
    assert report.rows[1].net_gain_inr == 62160.0
    assert report.net_stcg_inr == 16380.0
    assert report.net_ltcg_inr == 62160.0
    assert report.total_proceeds_inr == 184800.0 + 168000.0

    df = report.to_dataframe()
    assert len(df) == 2
    assert "Net Gain (₹)" in df.columns


def test_indian_tax_empty():
    rep = compute_indian_tax_report(pd.DataFrame())
    assert rep.trades_count == 0
    assert rep.to_dataframe().empty


def test_parse_trades_csv_vested_format():
    csv_text = """Symbol,Side,Date,Quantity,Price,Fees,Notes
NVDA,BUY,2026-10-01 15:30,15,120.50,1.20,Breakout setup
NVDA,SELL,2026-10-20 15:30,15,135.00,1.50,Target 1 exit
"""
    fills, warnings = importer.parse_trades_csv(csv_text)
    assert len(warnings) == 0
    assert len(fills) == 2
    assert fills[0].ticker == "NVDA"
    assert fills[0].side == "BUY"
    assert fills[0].qty == 15.0
    assert fills[0].price == 120.50
    assert fills[0].commission == 1.20
    assert fills[0].error is None

    assert fills[1].side == "SELL"
    assert fills[1].price == 135.00


def test_parse_trades_csv_invalid_rows():
    csv_text = """ticker,side,date,qty,price
,BUY,2026-10-01,10,100
AAPL,HOLD,2026-10-01,10,100
AAPL,BUY,not-a-date,10,100
AAPL,BUY,2026-10-01,0,100
AAPL,BUY,2026-10-01,10,-50
"""
    fills, _ = importer.parse_trades_csv(csv_text)
    assert len(fills) == 5
    assert all(f.error is not None for f in fills)


def test_execute_import_roundtrip():
    cfg = TradingSettings(starting_capital_usd=1000.0)
    csv_text = """ticker,side,date,qty,price,commission
TSLA,BUY,2026-10-01 16:00,5,200.00,1.00
TSLA,SELL,2026-10-15 16:00,5,220.00,1.00
"""
    fills, _ = importer.parse_trades_csv(csv_text)
    res = importer.execute_import(fills, cfg)
    assert res["imported_fills"] == 2
    assert res["new_trades"] == 1
    assert res["exits_recorded"] == 1
    assert len(res["errors"]) == 0

    trades = load_trades()
    assert len(trades) == 1
    t = trades[0]
    assert t.ticker == "TSLA"
    assert t.status == "CLOSED"
    assert len(t.fills) == 2


def test_screenshot_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGOS_DATA_DIR", str(tmp_path / "data"))
    img_data = b"\x89PNG\r\n\x1a\nfake_image_bytes"
    saved_path = screenshots.save_screenshot(42, img_data, "my_chart.png")

    p = Path(saved_path)
    assert p.exists()
    assert p.read_bytes() == img_data
    assert "trade_42_" in p.name

    listed = screenshots.list_screenshots(42)
    assert len(listed) == 1
    assert listed[0] == p


def test_alert_notifications_mock():
    cfg = TradingSettings(
        alert_ntfy_topic="test_topic",
        alert_telegram_bot_token="test_token",
        alert_telegram_chat_id="12345",
        alert_webhook_url="https://example.com/webhook",
    )

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        results = send_alert_notification("Test Alert", "Price hit 150", cfg)
        assert results["ntfy"] is True
        assert results["telegram"] is True
        assert results["webhook"] is True
        assert mock_post.call_count == 3


def test_test_notification_none_configured():
    cfg = TradingSettings()
    out = check_notifications(cfg)
    assert "none" in out


def test_provider_connections_mock():
    from tradingos.data.providers import (
        fetch_finnhub_earnings,
        fetch_finnhub_news,
        test_finnhub_connection,
        test_fmp_connection,
        test_fred_connection,
    )

    with patch("requests.get") as mock_get:
        # Mock Finnhub quote
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"c": 350.0}
        mock_get.return_value = mock_resp

        with patch("tradingos.data.providers.load_config") as mock_cfg:
            mock_cfg.return_value.finnhub_api_key = "fake_fh"
            ok, msg = test_finnhub_connection()
            assert ok is True
            assert "$350.00" in msg

        # Mock FMP quote
        mock_resp.json.return_value = [{"symbol": "AAPL", "price": 350.0}]
        with patch("tradingos.data.providers.load_config") as mock_cfg:
            mock_cfg.return_value.fmp_api_key = "fake_fmp"
            ok, msg = test_fmp_connection()
            assert ok is True
            assert "$350.00" in msg

        # Mock FRED observations
        mock_resp.json.return_value = {"observations": [{"date": "2026-11-20", "value": "4.45"}]}
        with patch("tradingos.data.providers.load_config") as mock_cfg:
            mock_cfg.return_value.fred_api_key = "fake_fred"
            ok, msg = test_fred_connection()
            assert ok is True
            assert "Connected" in msg

        # Mock Finnhub earnings calendar
        mock_resp.json.return_value = {
            "earningsCalendar": [{"symbol": "AAPL", "date": "2027-01-27", "epsEstimate": 2.95}]
        }
        earn = fetch_finnhub_earnings("AAPL", "fake_token")
        assert earn is not None
        assert earn["next_date"] == date(2027, 1, 27)

        # Mock Finnhub company news
        mock_resp.json.return_value = [
            {"headline": "Apple reports record quarter", "source": "Reuters", "url": "https://example.com/1", "datetime": 1795467600}
        ]
        news = fetch_finnhub_news("AAPL", "fake_token")
        assert len(news) == 1
        assert news[0]["headline"] == "Apple reports record quarter"
