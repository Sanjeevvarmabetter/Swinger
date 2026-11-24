from datetime import date, datetime

import pytest

from tradingos.db.models import ImmutableFieldError, Trade
from tradingos.db.session import session_scope
from tradingos.journal import service as js
from tradingos.settings import TradingSettings

CFG = TradingSettings()


def _open(**kw):
    args = dict(ticker="abc", setup="Breakout", entry_thesis="Base breakout on volume", planned_entry=20.0,
                initial_stop=19.0, target1=23.0, target2=25.0, fill_price=20.0, qty=3, filled_at=datetime(2026, 1, 5),
                commission=0.5, fx_cost=0.1, cfg=CFG, equity=300)
    args.update(kw)
    return js.open_trade(**args)


def test_open_and_full_close_r_multiple():
    tid = _open()
    r = js.record_exit(tid, qty=3, price=23.0, filled_at=datetime(2026, 1, 20), commission=0.4)
    assert r["status"] == "CLOSED"
    df = js.trades_dataframe("CLOSED")
    row = df.iloc[0]
    assert row["ticker"] == "ABC"
    assert row["realized_net"] == pytest.approx(9 - 0.5 - 0.1 - 0.4)
    assert row["initial_risk_usd"] == pytest.approx(3.0)
    assert row["r_multiple"] == pytest.approx((9 - 1.0) / 3, abs=0.01)
    assert row["holding_days"] == 15


def test_partial_exit_then_close():
    tid = _open(qty=4, fill_price=20.0)
    r = js.record_exit(tid, qty=2, price=22.0, filled_at=datetime(2026, 1, 10))
    assert r["status"] == "OPEN" and r["open_qty"] == 2
    assert r["realized_net"] == pytest.approx(4 - 0.3)  # half of entry fees allocated
    with pytest.raises(ValueError):
        js.record_exit(tid, qty=5, price=22.0, filled_at=datetime(2026, 1, 11))
    js.record_exit(tid, qty=2, price=19.0, filled_at=datetime(2026, 1, 12))
    row = js.trades_dataframe("CLOSED").iloc[0]
    assert row["realized_net"] == pytest.approx(4 - 2 - 0.6)


def test_original_thesis_is_immutable():
    tid = _open()
    with pytest.raises(ImmutableFieldError):
        with session_scope() as s:
            t = s.get(Trade, tid)
            t.entry_thesis = "rewritten after the fact"
    with pytest.raises(ImmutableFieldError):
        with session_scope() as s:
            s.get(Trade, tid).initial_stop = 10.0
    with session_scope() as s:
        assert s.get(Trade, tid).entry_thesis == "Base breakout on volume"


def test_reflection_fields_are_editable():
    tid = _open()
    js.update_reflection(tid, lessons="waited for confirmation", mistake_tags=["Chased entry"])
    row = js.trades_dataframe().iloc[0]
    assert row["lessons"] == "waited for confirmation" and row["mistake_tags"] == "Chased entry"


def test_stop_changes_and_widening_flag():
    tid = _open()
    assert js.change_stop(tid, 20.0, "breakeven")["widened"] is False
    assert js.change_stop(tid, 18.0, "gave it room")["widened"] is True
    row = js.trades_dataframe().iloc[0]
    assert row["stop_widened"] and row["stop_changes"] == 2 and row["current_stop"] == 18.0
    assert row["initial_stop"] == 19.0


def test_validation():
    with pytest.raises(ValueError):
        _open(entry_thesis="  ")
    with pytest.raises(ValueError):
        _open(initial_stop=21.0)
    with pytest.raises(ValueError):
        _open(qty=0)
    tid = _open()
    with pytest.raises(ValueError):
        js.record_exit(tid, qty=1, price=21, filled_at=datetime(2025, 1, 1))


def test_account_state_cash_math():
    js.add_capital_flow("DEPOSIT", 100, date(2026, 1, 2), fx_cost_usd=1.0)
    tid = _open(qty=4)  # cost 80 + 0.6 fees
    st = js.account_state(CFG, prices={"ABC": 21.0})
    assert st["net_contributed"] == 400
    assert st["cash"] == pytest.approx(400 - 1 - 80.6)
    assert st["equity_marked"] == pytest.approx(400 - 1 - 80.6 + 84)
    assert st["open_risk"] == pytest.approx(4.0)
    js.record_exit(tid, qty=4, price=21.0, filled_at=datetime(2026, 1, 9))
    st = js.account_state(CFG)
    assert st["cash"] == pytest.approx(400 - 1 + 4 - 0.6)
    assert st["equity_marked"] == st["equity_at_cost"]


def test_unpriced_positions_do_not_fake_unrealized():
    _open()
    st = js.account_state(CFG, prices={})
    assert st["unrealized_pnl"] is None and st["equity_marked"] is None and st["unpriced_positions"] == ["ABC"]


def test_csv_export_columns():
    _open()
    csv = js.trades_dataframe().to_csv(index=False)
    for col in ("ticker", "entry_thesis", "r_multiple", "fx_costs", "fees_total"):
        assert col in csv.splitlines()[0]


def test_unchanged_stop_rejected():
    tid = _open()
    with pytest.raises(ValueError, match="unchanged"):
        js.change_stop(tid, 19.0, "noop")
