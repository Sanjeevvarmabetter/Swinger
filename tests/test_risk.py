import pytest

from tradingos.risk.engine import (Check, OpenPositionRisk, evaluate_trade, floor_to_increment, position_size,
                                   round_trip_costs, verdict_from_checks)
from tradingos.settings import TradingSettings


def cfg(**kw):
    return TradingSettings(spread_bps=0, slippage_bps=0, **kw)


def test_position_size_floor():
    p = position_size(300, 1, entry=20.0, stop=19.0)
    assert p.risk_budget == 3.0 and p.risk_per_share == 1.0 and p.shares == 3
    p = position_size(300, 1, entry=20.0, stop=18.9)  # 3/1.1 = 2.72 → 2
    assert p.shares == 2


def test_position_size_fractional_increment():
    p = position_size(300, 1, entry=200.0, stop=190.0, share_increment=0.01)  # 0.3 shares
    assert p.shares == pytest.approx(0.3)
    assert not p.unsuitable


def test_one_share_exceeds_budget_is_unsuitable():
    p = position_size(300, 1, entry=165.0, stop=138.6)
    assert p.unsuitable and p.shares == 0
    assert "unsuitable" in p.message.lower()


def test_cash_cap_no_leverage():
    p = position_size(300, 1, entry=10.0, stop=9.99, cash_available=50)  # risk says 300 shares
    assert p.shares == 5 and p.limited_by == "cash"


def test_invalid_inputs():
    assert position_size(300, 1, 10, 10).limited_by == "invalid"
    assert position_size(0, 1, 10, 9).limited_by == "invalid"


def test_floor_to_increment_float_safety():
    assert floor_to_increment(0.3, 0.1) == pytest.approx(0.3)
    assert floor_to_increment(2.9999999999, 1) == 3  # float noise tolerated
    assert floor_to_increment(2.99, 1) == 2


def test_costs():
    c = round_trip_costs(10, 11, 10, TradingSettings(commission_per_order_usd=1, commission_pct=0, spread_bps=10,
                                                     slippage_bps=10, fx_markup_pct=1, include_fx_in_trade_costs=True))
    assert c["commission"] == 2
    assert c["spread"] == pytest.approx(0.21)
    assert c["fx"] == pytest.approx(2.1)


def test_min_commission():
    c = round_trip_costs(10, 10, 1, TradingSettings(commission_pct=0.1, commission_min_usd=1, spread_bps=0, slippage_bps=0))
    assert c["commission"] == 2


def test_evaluate_eligible():
    ev = evaluate_trade("ABC", 20, 19, 23, 25, 300, 300, [], cfg())
    assert ev.verdict == "Plan eligible", ev.verdict_reasons
    assert ev.size.shares == 3 and ev.rr_t1 == pytest.approx(3.0)


def test_evaluate_poor_rr_is_avoid():
    ev = evaluate_trade("ABC", 20, 19, 20.5, 21, 300, 300, [], cfg())
    assert ev.verdict == "Avoid"


def test_evaluate_rr_below_min_is_wait():
    ev = evaluate_trade("ABC", 20, 19, 21.5, 22, 300, 300, [], cfg())
    assert ev.verdict == "Wait"


def test_aggregate_risk_limit():
    open_pos = [OpenPositionRisk("X", 3, 20, 19), OpenPositionRisk("Y", 3, 20, 19)]  # $6 open risk = 2%
    ev = evaluate_trade("ABC", 20, 19, 23, 25, 300, 180, open_pos, cfg())
    assert ev.verdict == "Wait"
    assert any(c.name.startswith("Aggregate") and not c.passed for c in ev.checks)


def test_max_positions():
    open_pos = [OpenPositionRisk(t, 1, 10, 10) for t in "XYZ"]  # risk-free (stop at entry) but 3 slots used
    ev = evaluate_trade("ABC", 20, 19, 23, 25, 300, 200, open_pos, cfg())
    assert any(c.name == "Max simultaneous positions" and not c.passed for c in ev.checks)


def test_no_adding_to_existing():
    ev = evaluate_trade("ABC", 20, 19, 23, 25, 300, 200, [OpenPositionRisk("ABC", 1, 20, 20)], cfg())
    assert ev.verdict != "Plan eligible"


def test_stop_above_entry_is_avoid():
    ev = evaluate_trade("ABC", 20, 21, 23, 25, 300, 300, [], cfg())
    assert ev.verdict == "Avoid"


def test_locked_in_position_has_zero_risk():
    assert OpenPositionRisk("A", 5, 10, 11).risk == 0


def test_verdict_precedence():
    assert verdict_from_checks([Check("a", False, "x", "hard"), Check("b", False, "y", "soft")])[0] == "Avoid"
    assert verdict_from_checks([Check("b", False, "y", "soft"), Check("c", False, "z", "info")])[0] == "Wait"
    assert verdict_from_checks([Check("c", False, "z", "info")])[0] == "Watch"
    assert verdict_from_checks([Check("c", True, "z")])[0] == "Plan eligible"


def test_check_is_json_safe_with_numpy_bool():
    import json
    from dataclasses import asdict

    import numpy as np
    c = Check("x", np.bool_(True), "d")
    assert type(c.passed) is bool
    json.dumps(asdict(c))
