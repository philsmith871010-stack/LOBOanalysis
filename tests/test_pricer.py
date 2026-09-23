import QuantLib as ql
from pricer import Market, CallableSwap, price, fair_rate
from pricer.data import LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE


def test_live_40y_semi_2_15_at_fair():
    mkt = Market(LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE)
    r = price(mkt, CallableSwap(40, 0.011))
    assert abs(r["par"] - 0.04905) < 0.0003
    assert abs(r["cancel_right"] / 6.61e6 - 1) < 0.02
    assert abs(r["best_european"] / 6.00e6 - 1) < 0.02
    assert 1.08 < r["multiple"] < 1.12
    assert abs(r["bank_take"]) < 60e3


def test_fair_rate_solver():
    mkt = Market(LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE)
    k, r = fair_rate(mkt, CallableSwap(40, 0.02))
    assert abs(k - 0.0110) < 0.0006 and abs(r["bank_take"]) < 30e3
