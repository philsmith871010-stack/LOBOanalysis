"""Slower, second-tier results: sensitivities, exercise probabilities / expected life, collateral scenarios."""
from dataclasses import replace
import numpy as np
from scipy.stats import norm
from .structure import price

Y = np.linspace(-8, 8, 321); DY = Y[1] - Y[0]


def sensitivities(mkt, s, res):
    """Bank's take per +10 bp of our rate; cancel right per +10 bp of normal vol; cancel right at reversion 1% and 2% (what a bank buying the option is likely to show)."""
    up = price(mkt, replace(s, rate=s.rate + 0.001), europeans=False)
    vol = price(mkt.shifted(vol_bump=0.0010), s, europeans=False)
    r1 = price(mkt.shifted(reversion=0.01), s, europeans=False)
    r2 = price(mkt.shifted(reversion=0.02), s, europeans=False)
    return dict(take_per_10bp_rate=up["bank_take"] - res["bank_take"], cancel_per_10bp_vol=vol["cancel_right"] - res["cancel_right"],
                cancel_rev1=r1["cancel_right"], cancel_rev2=r2["cancel_right"])


def exercise_profile(mkt, s, res, npath=20000, sub=6, seed=7):
    """Risk-neutral probability that the bank cancels on each ticked date (and never), from the calibrated model.
    Backward induction on a state grid gives the exercise boundary; Monte Carlo with Radon-Nikodym weights turns
    numeraire-measure paths into risk-neutral probabilities. Returns dict(by_period={k: prob}, never=prob, expected_life=y, cum_by_year={y: prob})."""
    m, fd, ex, calls, K, N = res["_model"], res["_fd"], res["_ex"], res["_calls"], s.rate, s.notional
    sp = m.stateProcess(); yf = mkt.yf
    t_ex = [yf(d) for d in ex]; n = len(ex)
    tau = np.array([mkt.dc.yearFraction(fd[j], fd[j + 1]) for j in range(len(fd) - 1)])
    E = np.zeros((n, len(Y)))                      # exercise value / numeraire on the grid
    for i, (te, k) in enumerate(zip(t_ex, calls)):
        Ti = [yf(x) for x in fd[k:]]
        for g, y in enumerate(Y):
            P = [m.zerobond(Tj, te, y) for Tj in Ti]
            E[i, g] = N * (P[0] - P[-1] - K * sum(t * p for t, p in zip(tau[k:], P[1:]))) / m.numeraire(te, y)

    def trans(t0, t1):
        x0 = sp.expectation(0.0, 0.0, t0) + Y * sp.stdDeviation(0.0, 0.0, t0)
        mu1, sd1 = sp.expectation(0.0, 0.0, t1), sp.stdDeviation(0.0, 0.0, t1)
        Pm = np.zeros((len(Y), len(Y)))
        for g, x in enumerate(x0):
            w = norm.pdf(Y, (sp.expectation(t0, x, t1 - t0) - mu1) / sd1, sp.stdDeviation(t0, x, t1 - t0) / sd1) * DY
            Pm[g] = w / w.sum()
        return Pm

    V = np.maximum(E[-1], 0.0); ystar = np.full(n, np.inf)
    if (E[-1] > 0).any(): ystar[-1] = Y[np.argmax(E[-1] > 0)]
    for i in range(n - 2, -1, -1):
        C = trans(t_ex[i], t_ex[i + 1]) @ V; exr = E[i] > C
        if exr.any(): ystar[i] = Y[np.argmax(exr)]
        V = np.where(exr, E[i], C)

    rng = np.random.default_rng(seed); tt = [0.0] + t_ex
    x = np.zeros(npath); logB = np.zeros(npath); alive = np.ones(npath, bool); N0 = m.numeraire(0.0, 0.0)
    r0 = -np.log(mkt.curve.discount(1 / 365)) * 365
    q = {}
    for i in range(n):
        for st in range(sub):
            t0 = tt[i] + (tt[i + 1] - tt[i]) * st / sub; t1 = tt[i] + (tt[i + 1] - tt[i]) * (st + 1) / sub; dt = t1 - t0
            if t0 > 0:
                r_grid = np.array([-np.log(m.zerobond(t0 + 1 / 365, t0, y)) * 365 for y in Y])
                logB += np.interp((x - sp.expectation(0.0, 0.0, t0)) / sp.stdDeviation(0.0, 0.0, t0), Y, r_grid) * dt
            else:
                logB += r0 * dt
            e0, e1 = sp.expectation(t0, 0.0, dt), sp.expectation(t0, 1.0, dt)
            x = e0 + (e1 - e0) * x + sp.stdDeviation(t0, 0.0, dt) * rng.standard_normal(npath)
        te = tt[i + 1]; y = (x - sp.expectation(0.0, 0.0, te)) / sp.stdDeviation(0.0, 0.0, te)
        w = np.exp(logB) * N0 / np.interp(y, Y, [m.numeraire(te, yy) for yy in Y])
        hit = alive & (y >= ystar[i]); q[calls[i]] = float((w * hit).mean()); alive &= ~hit
        if i == n - 1: never = float((w * alive).mean())
    tot = sum(q.values()) + never; q = {k: v / tot for k, v in q.items()}; never /= tot
    ppy = 12 // s.freq_months
    life = sum(k / ppy * p for k, p in q.items()) + never * s.term_years
    cum = {yr: sum(p for k, p in q.items() if k <= yr * ppy) for yr in sorted({int(np.ceil(k / ppy)) for k in q} | {5, 10, 15})}
    return dict(by_period=q, never=never, expected_life=life, cum_by_year=cum)


def collateral(mkt, s, res, shifts=(-0.005, -0.01, -0.02, -0.03)):
    """What the investor would post today if the whole curve moved: the bank's package (receiver swap + cancel right)
    is re-valued on the shifted curve with the smile re-anchored to the new forwards. Posting = increase in the package value."""
    v0 = res["bank_take"]                      # bank's package value today (receiver swap + cancel right) = its take
    out = {}
    for sh in shifts:
        r = price(mkt.shifted(curve_shift=sh), s, europeans=False)
        out[int(round(sh * 1e4))] = max(0.0, (r["cancel_right"] - r["coupon_discount"]) - v0)
    return out
