"""Coupon schedule of the cancellable swap with per-period cashflows, PVs and per-date cancellation metrics."""
import QuantLib as ql

COLUMNS = ["#", "Start", "End", "Pay date", "Accrual (y)", "Fixed cashflow £", "Projected SONIA cashflow £", "Net cashflow £",
           "Discount factor", "PV of net £", "Cancel here?", "Exercise date", "Forward swap rate from here", "Strike - forward (bp)",
           "Remaining annuity £ per 1%", "Intrinsic if cancelled here £", "European value at this date £", "Normal vol at strike (bp)", "Probability cancelled here"]


def _d(d):
    return "%04d-%02d-%02d" % (d.year(), d.month(), d.dayOfMonth())


def build_schedule(mkt, term_years, freq_months, rate, notional, ticks=None):
    """One row per coupon period. `ticks` is a dict {period index: bool} to carry over; default: no ticks.
    Fixed cashflows are what we pay; SONIA cashflows are projected off the curve; net is from our side (receive SONIA - pay fixed)."""
    swap = mkt.swap(0, term_years * 12, rate, freq_months, notional)
    fd = list(swap.fixedSchedule()); n = len(fd) - 1
    fixed = [ql.as_coupon(c) for c in swap.leg(0)]; flt = [ql.as_floating_rate_coupon(c) for c in swap.leg(1)]
    rows = []
    for k in range(n):
        start, end = fd[k], fd[k + 1]; pay = fixed[k].date()
        acc = mkt.dc.yearFraction(start, end)
        fx, fl = fixed[k].amount(), flt[k].amount()
        df = mkt.curve.discount(pay); net = fl - fx
        ex = mkt.cal.advance(start, -2, ql.Days)
        if k > 0:
            fwd = mkt.swap(k * freq_months, term_years * 12 - k * freq_months, rate, freq_months, notional)
            F = fwd.fairRate(); rem = list(fwd.fixedSchedule())
            ann = sum(mkt.dc.yearFraction(rem[j], rem[j + 1]) * mkt.curve.discount(rem[j + 1]) for j in range(len(rem) - 1)) * notional
            intrinsic = max(0.0, (F - rate) * ann)          # value to the bank of cancelling on this date, today's curve
        else:
            F, ann, intrinsic = swap.fairRate(), None, 0.0
        rows.append({"#": k, "Start": _d(start), "End": _d(end), "Pay date": _d(pay), "Accrual (y)": round(acc, 4),
                     "Fixed cashflow £": round(-fx), "Projected SONIA cashflow £": round(fl), "Net cashflow £": round(net),
                     "Discount factor": round(df, 6), "PV of net £": round(net * df), "Cancel here?": bool(ticks.get(k, False)) if ticks else False,
                     "Exercise date": _d(ex) if k > 0 else "", "Forward swap rate from here": round(F, 6),
                     "Strike - forward (bp)": round((rate - F) * 1e4, 1), "Remaining annuity £ per 1%": round(ann / 100) if ann else "",
                     "Intrinsic if cancelled here £": round(intrinsic), "European value at this date £": "", "Normal vol at strike (bp)": "", "Probability cancelled here": ""})
    return rows, swap.NPV()


def preset_ticks(name, term_years, freq_months):
    """Standard call schedules by name -> set of period indices."""
    ppy = 12 // freq_months; name = (name or "").strip().lower()
    if name in ("semi-annual 2-15", "semi 2-15", "2-15 semi"): return set(range(2 * ppy, 15 * ppy + 1))
    if name in ("annual 2-15", "2-15 annual"): return set(range(2 * ppy, 15 * ppy + 1, ppy))
    if name in ("annual 3-10",): return set(range(3 * ppy, 10 * ppy + 1, ppy))
    if name in ("six dates", "6 dates"): return {y * ppy for y in (2, 3, 5, 7, 10, 15)}
    if name in ("single 2y", "european 2y"): return {2 * ppy}
    if name in ("full strip", "all"): return set(range(1 * ppy, term_years * ppy))
    if name in ("none", "clear"): return set()
    return None
