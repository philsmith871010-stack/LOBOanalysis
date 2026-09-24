"""Market data: SONIA OIS curve and a normal-vol swaption surface with a shifted-SABR smile per row."""
import math
import numpy as np
import QuantLib as ql
from scipy.optimize import least_squares

SHIFT, BETA = 0.02, 0.5


def _nvol_from_sabr(p, F, K, T):
    a, rho, nu = p
    lnv = ql.shiftedSabrVolatility(K, F, T, a, BETA, nu, rho, SHIFT)
    px = ql.blackFormula(ql.Option.Call, K + SHIFT, F + SHIFT, lnv * math.sqrt(T))
    return ql.bachelierBlackFormulaImpliedVol(ql.Option.Call, K, F, T, px)


class Market:
    """
    curve:   list of (tenor string like '10Y', par OIS rate in %)
    surface: list of (expiry_years, tenor_years, atm_strike_pct, {offset_bp: normal_vol_bp, ...})
    """

    def __init__(self, asof, curve, surface, reversion=0.03, fits=None, vol_bump=0.0):
        self.asof = asof; self.curve_rows = list(curve); self.surface_rows = list(surface); self.vol_bump = vol_bump
        ql.Settings.instance().evaluationDate = asof
        self.cal, self.dc = ql.UnitedKingdom(), ql.Actual365Fixed()
        self.reversion = reversion
        helpers = [ql.OISRateHelper(0, ql.Period(t), ql.QuoteHandle(ql.SimpleQuote(r / 100)), ql.Sonia(),
                                    ql.YieldTermStructureHandle(), True, 0, ql.Following, ql.Annual, self.cal)
                   for t, r in curve]
        self.curve = ql.PiecewiseLogLinearDiscount(0, self.cal, helpers, self.dc)
        self.curve.enableExtrapolation()
        self.h = ql.YieldTermStructureHandle(self.curve)
        self.index = {m: ql.IborIndex("SONIA-%dM" % m, ql.Period(m, ql.Months), 0, ql.GBPCurrency(), self.cal,
                                      ql.ModifiedFollowing, False, self.dc, self.h) for m in (6, 12)}
        self.disc_engine = ql.DiscountingSwapEngine(self.h)
        self.fits = dict(fits) if fits else {}
        for e, t, atm, vols in ([] if fits else surface):
            F = atm / 100
            Ks = [F + o / 1e4 for o in vols]
            mkt = np.array([vols[o] for o in vols]) / 1e4
            res = least_squares(lambda p: [_nvol_from_sabr(p, F, K, e) - v for K, v in zip(Ks, mkt)],
                                x0=[0.03, -0.2, 0.4], bounds=([1e-4, -0.999, 1e-4], [5, 0.999, 5]))
            self.fits[(e, t)] = (F, res.x, max(abs(res.fun)) * 1e4)

    def shifted(self, curve_shift=0.0, vol_bump=0.0, reversion=None):
        """Same market with every OIS rate moved by `curve_shift` (decimal) and/or every normal vol by `vol_bump` (decimal);
        the SABR fits are reused, so this is cheap."""
        return Market(self.asof, [(t, r + curve_shift * 100) for t, r in self.curve_rows], self.surface_rows,
                      reversion=self.reversion if reversion is None else reversion, fits=self.fits, vol_bump=self.vol_bump + vol_bump)

    def yf(self, d):
        return self.dc.yearFraction(self.asof, d)

    def swap(self, start_months, tenor_months, rate, freq_months, nominal):
        start = self.cal.advance(self.asof, ql.Period(start_months, ql.Months))
        return ql.MakeVanillaSwap(ql.Period(tenor_months, ql.Months), self.index[freq_months], rate, ql.Period(0, ql.Days),
                                  effectiveDate=start, fixedLegTenor=ql.Period(freq_months, ql.Months),
                                  fixedLegDayCount=self.dc, pricingEngine=self.disc_engine, nominal=nominal)

    def nvol(self, expiry_y, tenor_y, offset):
        """Normal vol at moneyness offset (K - F), interpolated over the ragged (expiry, tenor) grid."""
        by_exp = {}
        for (e, t), (F, p, _) in self.fits.items():
            by_exp.setdefault(e, []).append((t, _nvol_from_sabr(p, F, F + offset, e)))
        exps = sorted(by_exp)
        vals = []
        for e in exps:
            pts = sorted(by_exp[e]); ts, vs = zip(*pts)
            vals.append(float(np.interp(tenor_y, ts, vs)))
        return float(np.interp(expiry_y, exps, vals)) + self.vol_bump

    def fit_report(self):
        return {k: round(v[2], 2) for k, v in self.fits.items()}
