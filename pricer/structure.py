"""Price a cancellable swap: bank holds the right to cancel (a payer Bermudan on the remaining swap)."""
from dataclasses import dataclass, field
from typing import List, Optional
import QuantLib as ql


@dataclass
class CallableSwap:
    term_years: int                       # swap term
    rate: float                           # fixed rate we pay, decimal (e.g. 0.0143)
    notional: float = 10e6
    freq_months: int = 6                  # coupon / call frequency (6 or 12)
    first_call_years: float = 2
    last_call_years: float = 15
    call_years: Optional[List[float]] = None   # explicit list overrides first/last
    call_periods_list: Optional[List[int]] = None  # explicit period indices (from the Schedule ticks) override everything

    def call_periods(self):
        ppy = 12 // self.freq_months
        if self.call_periods_list:
            return sorted(self.call_periods_list)
        if self.call_years:
            return [int(round(y * ppy)) for y in self.call_years]
        return list(range(int(round(self.first_call_years * ppy)), int(round(self.last_call_years * ppy)) + 1))


def price(mkt, s: CallableSwap, europeans=True, ladder_max=None):
    """Returns a dict with the bank's cancel-right value, what the coupon discount is worth, and the European ladder."""
    T, K, N, fm = s.term_years, s.rate, s.notional, s.freq_months
    ppy = 12 // fm
    swap = mkt.swap(0, T * 12, K, fm, N); fd = list(swap.fixedSchedule()); par = swap.fairRate()
    annuity = sum(mkt.dc.yearFraction(fd[j], fd[j + 1]) * mkt.curve.discount(fd[j + 1]) for j in range(len(fd) - 1)) * N
    calls = s.call_periods()
    ex = [mkt.cal.advance(fd[k], -2, ql.Days) for k in calls]
    helpers = []; nvols = {}
    for k in calls:
        F = mkt.swap(k * fm, T * 12 - k * fm, K, fm, 1.0).fairRate(); ty = k / ppy
        nvols[k] = mkt.nvol(ty, T - ty, K - F)
        helpers.append(ql.SwaptionHelper(ql.Period(k * fm, ql.Months), ql.Period(T * 12 - k * fm, ql.Months),
                                         ql.QuoteHandle(ql.SimpleQuote(mkt.nvol(ty, T - ty, K - F))), mkt.index[fm],
                                         ql.Period(fm, ql.Months), mkt.dc, mkt.dc, mkt.h,
                                         ql.BlackCalibrationHelper.RelativePriceError, K, 1.0, ql.Normal, 0.0))
    model = ql.Gsr(mkt.h, ex[:-1], [ql.QuoteHandle(ql.SimpleQuote(0.01))] * len(ex),
                   [ql.QuoteHandle(ql.SimpleQuote(mkt.reversion))], T + 1.0)
    engine = ql.Gaussian1dSwaptionEngine(model, 64, 7.0, True, False, mkt.h)
    for x in helpers: x.setPricingEngine(engine)
    model.calibrateVolatilitiesIterative(helpers, ql.LevenbergMarquardt(), ql.EndCriteria(1000, 10, 1e-8, 1e-8, 1e-8))
    berm = ql.Swaption(swap, ql.BermudanExercise(ex), ql.Settlement.Cash, ql.Settlement.CollateralizedCashPrice)
    berm.setPricingEngine(engine)
    value = berm.NPV()
    paid = (par - K) * annuity
    out = dict(par=par, annuity=annuity, cancel_right=value, coupon_discount=paid, bank_take=value - paid,
               calib_err=max(abs(h.calibrationError()) for h in helpers), n_calls=len(calls), nvols=nvols,
               _model=model, _swap=swap, _fd=fd, _ex=ex, _calls=calls)
    if europeans:
        ladder = []
        for k, d in list(zip(calls, ex))[:ladder_max] if ladder_max else zip(calls, ex):
            fwd = mkt.swap(k * fm, T * 12 - k * fm, K, fm, N)
            e = ql.Swaption(fwd, ql.EuropeanExercise(d), ql.Settlement.Cash, ql.Settlement.CollateralizedCashPrice)
            e.setPricingEngine(engine)
            ladder.append((k / ppy, e.NPV(), fwd.NPV(), k))
        best = max(ladder, key=lambda r: r[1])
        out.update(europeans=ladder, best_european=best[1], best_european_expiry=best[0], intrinsic=best[2],
                   multiple=value / best[1], time_value=value - best[1])
    return out
