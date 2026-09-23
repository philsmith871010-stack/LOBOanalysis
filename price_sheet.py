"""Price the cancellable swap described in a Google Sheet and write the results back.

    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --once
    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --watch     # poll Settings!Run every 20s

Tabs: Curve, Vols, Settings, Structure, Schedule (one row per coupon period; tick "Cancel here?"), Results.
The ticked rows on Schedule ARE the call schedule. Structure!Preset (e.g. "semi-annual 2-15", "six dates",
"single 2y", "full strip", "none") sets the ticks on the next run and is then cleared.
"""
import argparse, datetime as dt, re, time
import gspread
import QuantLib as ql
from pricer import Market, CallableSwap, price, rate_for_take, build_schedule, preset_ticks, SCHEDULE_COLUMNS
from pricer.data import surface_from_rows

KEY_CELL = "Z1"    # Schedule!Z1 holds "term|freq" of the schedule currently laid out


def open_sheet(ref, keyfile):
    gc = gspread.service_account(filename=keyfile)
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", ref)
    return gc.open_by_key(m.group(1) if m else ref)


def kv(ws):
    return {r[0].strip(): (r[1] if len(r) > 1 else "") for r in ws.get_all_values() if r and r[0]}


def parse_asof(s):
    y, m, d = (int(x) for x in re.split(r"[-/]", str(s).strip())[:3])
    if y < 100: y, d = d, y
    return ql.Date(d, m, y)


def read_market(sh, st):
    curve = [(r[0].strip().upper(), float(r[1])) for r in sh.worksheet("Curve").get_all_values()[1:] if r and r[0] and r[1]]
    vrows = sh.worksheet("Vols").get_all_values()
    offsets = [int(float(x)) for x in vrows[0][3:] if x != ""]
    surface = surface_from_rows(offsets, [[c if c != "" else None for c in r] for r in vrows[1:] if r and r[0] and r[1]])
    return Market(parse_asof(st["As-of date"]), curve, surface, reversion=float(st["Mean reversion"]))


def get_ws(sh, name, rows=200, cols=30):
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(name, rows, cols)


def sync_schedule(sh, mkt, term, freq, rate, notional, preset):
    """Rebuild the Schedule rows for (term, freq); keep ticks where the period still exists; apply a preset if given."""
    ws = get_ws(sh, "Schedule")
    vals = ws.get_all_values()
    key = ws.acell(KEY_CELL).value
    ticks = {}
    if key == "%d|%d" % (term, freq) and len(vals) > 1:
        col = SCHEDULE_COLUMNS.index("Cancel here?")
        for r in vals[1:]:
            if r and r[0] != "" and len(r) > col:
                ticks[int(float(r[0]))] = str(r[col]).strip().upper() == "TRUE"
    p = preset_ticks(preset, term, freq) if preset else None
    if p is not None:
        ticks = {k: (k in p) for k in range(term * 12 // freq)}
    rows, npv = build_schedule(mkt, term, freq, rate, notional, ticks)
    ws.clear()
    ws.update("A1", [SCHEDULE_COLUMNS] + [[r[c] for c in SCHEDULE_COLUMNS] for r in rows])
    ws.update(KEY_CELL, [["%d|%d" % (term, freq)]])
    return ws, rows, [r["#"] for r in rows if r["Cancel here?"]], npv


def write_per_date(ws, rows, result):
    eur = {k: v for (_, v, _, k) in result["europeans"]}
    c_e = SCHEDULE_COLUMNS.index("European value at this date £") + 1; c_v = SCHEDULE_COLUMNS.index("Normal vol at strike (bp)") + 1
    cells = []
    for r in rows:
        k = r["#"]
        if k in eur:
            cells.append(gspread.Cell(k + 2, c_e, round(eur[k]))); cells.append(gspread.Cell(k + 2, c_v, round(result["nvols"][k] * 1e4, 1)))
    if cells: ws.update_cells(cells)


def run(sh):
    st = kv(sh.worksheet("Settings")); sr = kv(sh.worksheet("Structure"))
    mkt = read_market(sh, st)
    notional = float(str(st["Notional"]).replace(",", ""))
    term = int(float(sr["Term (years)"])); freq = int(float(sr["Frequency (months)"]))
    rate_in = str(sr["Fixed rate %"]).strip().lower()
    K = 0.02 if rate_in in ("fair", "solve") else float(rate_in.replace("%", "")) / 100
    res_ws = get_ws(sh, "Results"); res_ws.update("B1", [["running..."]])
    sched_ws, rows, calls, swap_npv = sync_schedule(sh, mkt, term, freq, K, notional, sr.get("Preset", ""))
    if sr.get("Preset", ""):
        ws = sh.worksheet("Structure"); c = ws.find("Preset"); ws.update_cell(c.row, 2, "")
    if not calls:
        res_ws.update("B1", [["no dates ticked on Schedule"]]); return None
    spec = dict(term_years=term, notional=notional, freq_months=freq, call_periods_list=calls)
    out = []
    if rate_in in ("fair", "solve"):
        k, r = rate_for_take(mkt, CallableSwap(rate=0.02, **spec), 0.0)
        kc, _ = rate_for_take(mkt, CallableSwap(rate=k, **spec), float(st["Bank take, collateral £"]))
        kn, _ = rate_for_take(mkt, CallableSwap(rate=kc, **spec), float(st["Bank take, no collateral £"]))
        out += [["Model-fair rate %", round(k * 100, 3)], ["Dealt rate, collateral %", round(kc * 100, 3)], ["Dealt rate, no collateral %", round(kn * 100, 3)]]
        K = k
        sched_ws, rows, calls, swap_npv = sync_schedule(sh, mkt, term, freq, K, notional, "")
    else:
        r = price(mkt, CallableSwap(rate=K, **spec))
    bump = price(mkt, CallableSwap(rate=K + 0.001, **spec), europeans=False)
    per10bp = -(bump["bank_take"] - r["bank_take"])
    out += [["Fixed rate priced %", round(K * 100, 3)], ["Par swap rate %", round(r["par"] * 100, 3)], ["Swap value to us (Schedule PV) £", round(swap_npv)],
            ["Annuity £ per 1%", round(r["annuity"] / 100)], ["Cancel right, value to bank £", round(r["cancel_right"])],
            ["Coupon discount, value to us £", round(r["coupon_discount"])], ["Bank's take £", round(r["bank_take"])],
            ["Intrinsic (forward swap) £", round(r["intrinsic"])], ["Best European £", round(r["best_european"])],
            ["Best European expiry (y)", r["best_european_expiry"]], ["Bermudan time value £", round(r["time_value"])],
            ["Multiple of best European", round(r["multiple"], 3)], ["£ per 10 bp of rate", round(per10bp)],
            ["Calibration error (max, relative)", round(r["calib_err"], 5)], ["Call dates ticked", r["n_calls"]]]
    res_ws.clear()
    res_ws.update("A1", [["Priced at", dt.datetime.now().strftime("%Y-%m-%d %H:%M")], ["Market as-of", st["As-of date"]],
                        ["Structure", "%dy swap, %d cancel dates (see Schedule)" % (term, len(calls))]] + out)
    ladder = [["European ladder (each ticked date on its own)", "", ""], ["Expiry (y)", "Value £", "Forward swap £"]] + [[e, round(v), round(i)] for e, v, i, _ in r["europeans"]]
    res_ws.update("E1", ladder)
    write_per_date(sched_ws, rows, r)
    return r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sheet", required=True); ap.add_argument("--key", default="sa-key.json")
    ap.add_argument("--once", action="store_true"); ap.add_argument("--watch", action="store_true"); ap.add_argument("--interval", type=int, default=20)
    a = ap.parse_args(); sh = open_sheet(a.sheet, a.key)
    if a.once or not a.watch:
        r = run(sh)
        if r: print("done: cancel right £%.0f, multiple %.3f" % (r["cancel_right"], r["multiple"]))
        return
    print("watching %s every %ds (tick Settings!Run to price)" % (sh.title, a.interval))
    while True:
        ws = sh.worksheet("Settings"); cell = ws.find("Run")
        if str(ws.cell(cell.row, 2).value).strip().upper() == "TRUE":
            try:
                t = time.time(); r = run(sh); msg = "ok %.0fs" % (time.time() - t) if r else "nothing ticked"
            except Exception as e:                       # noqa
                msg = "error: %s" % e
            ws.update_cell(cell.row, 2, "FALSE"); s = ws.find("Status"); ws.update_cell(s.row, 2, "%s %s" % (dt.datetime.now().strftime("%H:%M"), msg))
            print(msg)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
