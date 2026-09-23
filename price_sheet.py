"""Price the callable swap described in a Google Sheet and write the results back.

    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --once
    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --watch     # poll Settings!Run every 20s

The sheet layout is the one in the template (tabs Curve, Vols, Settings, Structure, Results).
"""
import argparse, datetime as dt, re, sys, time
import gspread
import QuantLib as ql
from pricer import Market, CallableSwap, price, rate_for_take
from pricer.data import surface_from_rows


def open_sheet(ref, keyfile):
    gc = gspread.service_account(filename=keyfile)
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", ref)
    return gc.open_by_key(m.group(1) if m else ref)


def read_inputs(sh):
    curve = [(r[0].strip().upper(), float(r[1])) for r in sh.worksheet("Curve").get_all_values()[1:] if r and r[0] and r[1]]
    vrows = sh.worksheet("Vols").get_all_values()
    offsets = [int(float(x)) for x in vrows[0][3:] if x != ""]
    surface = surface_from_rows(offsets, [[c if c != "" else None for c in r] for r in vrows[1:] if r and r[0]])
    st = {r[0].strip(): (r[1] if len(r) > 1 else "") for r in sh.worksheet("Settings").get_all_values() if r and r[0]}
    sr = {r[0].strip(): (r[1] if len(r) > 1 else "") for r in sh.worksheet("Structure").get_all_values() if r and r[0]}
    return curve, surface, st, sr


def parse_asof(s):
    y, m, d = (int(x) for x in re.split(r"[-/]", s.strip())[:3])
    if y < 100: y, d = d, y                 # dd/mm/yyyy
    return ql.Date(d, m, y)


def run(sh):
    curve, surface, st, sr = read_inputs(sh)
    mkt = Market(parse_asof(st["As-of date"]), curve, surface, reversion=float(st["Mean reversion"]))
    notional = float(str(st["Notional"]).replace(",", ""))
    calls = [float(x) for x in re.split(r"[,\s]+", str(sr.get("Explicit call years", "")).strip()) if x] or None
    spec = dict(term_years=int(float(sr["Term (years)"])), notional=notional, freq_months=int(float(sr["Frequency (months)"])),
                first_call_years=float(sr["First call (years)"]), last_call_years=float(sr["Last call (years)"]), call_years=calls)
    rate_in = str(sr["Fixed rate %"]).strip().lower()
    res_ws = sh.worksheet("Results")
    res_ws.update("B1", [["running..."]])
    rows = []
    if rate_in in ("fair", "solve"):
        k, r = rate_for_take(mkt, CallableSwap(rate=0.02, **spec), 0.0)
        kc, rc = rate_for_take(mkt, CallableSwap(rate=k, **spec), float(st["Bank take, collateral £"]))
        kn, rn = rate_for_take(mkt, CallableSwap(rate=kc, **spec), float(st["Bank take, no collateral £"]))
        rows += [["Model-fair rate %", round(k * 100, 3)], ["Dealt rate, collateral %", round(kc * 100, 3)], ["Dealt rate, no collateral %", round(kn * 100, 3)]]
        K = k
    else:
        K = float(rate_in.replace("%", "")) / 100
        r = price(mkt, CallableSwap(rate=K, **spec))
    bump = price(mkt, CallableSwap(rate=K + 0.001, **spec), europeans=False)
    per10bp = -(bump["bank_take"] - r["bank_take"])
    rows += [["Fixed rate priced %", round(K * 100, 3)], ["Par swap rate %", round(r["par"] * 100, 3)],
             ["Annuity £ per 1%", round(r["annuity"] / 100)], ["Cancel right, value to bank £", round(r["cancel_right"])],
             ["Coupon discount, value to us £", round(r["coupon_discount"])], ["Bank's take £", round(r["bank_take"])],
             ["Intrinsic (forward swap) £", round(r["intrinsic"])], ["Best European £", round(r["best_european"])],
             ["Best European expiry (y)", r["best_european_expiry"]], ["Bermudan time value £", round(r["time_value"])],
             ["Multiple of best European", round(r["multiple"], 3)], ["£ per 10 bp of rate", round(per10bp)],
             ["Calibration error (max, relative)", round(r["calib_err"], 5)], ["Call dates", r["n_calls"]]]
    ladder = [["European ladder", "", ""], ["Expiry (y)", "Value £", "Forward swap £"]] + [[e, round(v), round(i)] for e, v, i in r["europeans"]]
    res_ws.clear()
    res_ws.update("A1", [["Priced at", dt.datetime.now().strftime("%Y-%m-%d %H:%M")], ["Market as-of", st["As-of date"]],
                        ["Structure", "%dy, calls %s" % (spec["term_years"], calls or "%s-%sy every %sm" % (spec["first_call_years"], spec["last_call_years"], spec["freq_months"]))]] + rows)
    res_ws.update("E1", ladder)
    return r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sheet", required=True); ap.add_argument("--key", default="sa-key.json")
    ap.add_argument("--once", action="store_true"); ap.add_argument("--watch", action="store_true"); ap.add_argument("--interval", type=int, default=20)
    a = ap.parse_args(); sh = open_sheet(a.sheet, a.key)
    if a.once or not a.watch:
        r = run(sh); print("done: cancel right £%.0f, multiple %.3f" % (r["cancel_right"], r["multiple"])); return
    print("watching %s every %ds (tick Settings!Run to price)" % (sh.title, a.interval))
    while True:
        ws = sh.worksheet("Settings"); cell = ws.find("Run")
        if str(ws.cell(cell.row, 2).value).strip().upper() == "TRUE":
            try:
                t = time.time(); r = run(sh); msg = "ok %.0fs" % (time.time() - t)
            except Exception as e:                         # noqa
                msg = "error: %s" % e
            ws.update_cell(cell.row, 2, "FALSE"); st = ws.find("Status"); ws.update_cell(st.row, 2, "%s %s" % (dt.datetime.now().strftime("%H:%M"), msg))
            print(msg)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
