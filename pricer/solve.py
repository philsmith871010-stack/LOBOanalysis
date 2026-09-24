"""Fair rate (bank's take = 0) and the rate at which the bank keeps a given take, by secant on the take."""
from dataclasses import replace
from .structure import price


def rate_for_take(mkt, s, take=0.0, tol=25.0, max_iter=8):
    """Secant search for the fixed rate at which cancel_right - coupon_discount == take. Returns (rate, result)."""
    k0 = s.rate; r0 = price(mkt, replace(s, rate=k0), europeans=False); f0 = r0["bank_take"] - take
    k1 = k0 + 0.001 * (1 if f0 < 0 else -1)
    r1 = price(mkt, replace(s, rate=k1), europeans=False); f1 = r1["bank_take"] - take
    for _ in range(max_iter):
        if abs(f1) < tol: break
        k2 = k1 - f1 * (k1 - k0) / (f1 - f0) if f1 != f0 else k1 + 0.001
        k2 = min(max(k2, k1 - 0.01, -0.015), k1 + 0.01)        # at most 1% per step, never below -1.5% (the smile's shift is 2%)
        k0, f0 = k1, f1
        k1 = k2; r1 = price(mkt, replace(s, rate=k1), europeans=False); f1 = r1["bank_take"] - take
    return k1, price(mkt, replace(s, rate=k1))


def fair_rate(mkt, s):
    return rate_for_take(mkt, s, 0.0)
