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


def test_schedule_pv_matches_swap():
    from pricer import build_schedule, preset_ticks
    mkt = Market(LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE)
    rows, npv = build_schedule(mkt, 40, 6, 0.0143, 10e6)
    assert len(rows) == 80
    assert abs(sum(r["PV of net £"] for r in rows) - npv) < 2000
    ticks = preset_ticks("six dates", 40, 6)
    assert ticks == {4, 6, 10, 14, 20, 30}
    r = price(mkt, CallableSwap(40, 0.0143, call_periods_list=sorted(ticks)))
    assert r["n_calls"] == 6 and 5.5e6 < r["cancel_right"] < 6.5e6


def test_full_run_extras_on_six_dates():
    from pricer import sensitivities, exercise_profile, collateral
    mkt = Market(LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE)
    s = CallableSwap(40, 0.0143, call_periods_list=[4, 6, 10, 14, 20, 30])
    r = price(mkt, s)
    prof = exercise_profile(mkt, s, r)
    assert abs(sum(prof["by_period"].values()) + prof["never"] - 1) < 1e-6
    assert 3 < prof["expected_life"] < 8 and prof["cum_by_year"][15] > 0.9
    col = collateral(mkt, s, r, shifts=(-0.01,))
    assert 0.5e6 < col[-100] < 1.0e6
    sen = sensitivities(mkt, s, r)
    assert 20e3 < sen["take_per_10bp_rate"] < 80e3 and sen["cancel_rev2"] > sen["cancel_rev1"]


def test_short_first_call_calibrates():
    mkt = Market(LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE)
    r = price(mkt, CallableSwap(40, 0.00451, call_periods_list=list(range(1, 31))), europeans=False)
    assert r["calib_err"] < 0.02
