"""Price the cancellable swap described in a Google Sheet and write the results back.

    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --init     # build / repair the 3-tab layout (once)
    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --watch    # sit and price whenever Pricer!Run is ticked
    python price_sheet.py --sheet <sheet id or url> --key sa-key.json --once     # price now and exit

Tabs: Pricer (inputs, results, ladder, portfolio), Market (curve + vol surface), Schedule (one row per coupon period; tick "Cancel here?").
Run mode Quick prices the structure (about 10 s). Full adds sensitivities, exercise probabilities, expected life and collateral (about 1 min).
Typing 'fair' as the fixed rate solves the model-fair and dealt rates first (about 2 min).
"""
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
import argparse, datetime as dt, os, re, time
import gspread
from gspread.utils import ValueRenderOption
import QuantLib as ql
from pricer import Market, CallableSwap, price, rate_for_take, build_schedule, preset_ticks, SCHEDULE_COLUMNS
from pricer import sensitivities, exercise_profile, collateral
from pricer.data import surface_from_rows
from sheet_layout import CELL, ROW, PRICER, NOTES, KEY_CELL, PRESET_CELL, col_letter, get_ws, init_sheet, style_schedule

UNF = ValueRenderOption.unformatted
SC = {name: col_letter(i + 1) for i, name in enumerate(SCHEDULE_COLUMNS)}


# ---------------------------------------------------------------- reading the sheet
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


def open_sheet(ref, keyfile=None):
    """A key file on the Mac; on Cloud Run the service's own identity (share the sheet with that account)."""
    if keyfile and os.path.exists(keyfile):
        gc = gspread.service_account(filename=keyfile)
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES); gc = gspread.authorize(creds)
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", ref)
    return gc.open_by_key(m.group(1) if m else ref)


def pct(v):
    """A rate cell: 0.0143 from a percent-formatted cell, or 1.43 if someone pasted a plain number over it."""
    v = float(str(v).replace("%", "").replace(",", ""))
    return v / 100 if v > 0.5 else v


def parse_date(v):
    if isinstance(v, (int, float)):                                   # a real date cell comes back as a serial number
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(v)); return ql.Date(d.day, d.month, d.year)
    y, m, d = (int(x) for x in re.split(r"[-/]", str(v).strip())[:3])
    if y < 100: y, d = d, y
    return ql.Date(d, m, y)


def read_inputs(sh):
    ws = sh.worksheet("Pricer")
    col = ws.get("B1:B%d" % max(ROW.values()), value_render_option=UNF)
    v = lambda label: (col[ROW[label] - 1][0] if len(col) >= ROW[label] and col[ROW[label] - 1] else "")
    rate = str(v("Fixed rate we pay")).strip().lower()
    return dict(term=int(float(v("Term (years)"))), rate=("fair" if rate in ("fair", "solve") else pct(rate)),
                freq=int(float(v("Coupon frequency (months)"))), notional=float(str(v("Notional")).replace(",", "")),
                preset=str(v("Call dates")).strip(), mode=str(v("Run mode")).strip().lower() or "quick",
                reversion=pct(v("Mean reversion")), take_c=float(v("Bank take, collateral")), take_n=float(v("Bank take, no collateral")))


def read_market(sh, reversion):
    v = sh.worksheet("Market").get_values(value_render_option=UNF)
    asof = parse_date(v[0][1])
    curve, i = [], 4
    while i < len(v) and v[i] and str(v[i][0]).strip() != "":
        curve.append((str(v[i][0]).strip().upper(), pct(v[i][1]) * 100)); i += 1
    head = v[3][6:]; offsets = [int(float(x)) for x in head if x != ""]
    rows = []
    for r in v[4:]:
        if len(r) > 5 and r[3] != "":
            rows.append([float(r[3]), float(r[4]), pct(r[5]) * 100, *[x if x != "" else None for x in r[6:6 + len(offsets)]]])
    return Market(asof, curve, surface_from_rows(offsets, rows), reversion=reversion), asof


# ---------------------------------------------------------------- writing the sheet
def status(sh, msg):
    sh.worksheet("Pricer").update(range_name=CELL["Status"], values=[["%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)]])
    print(msg, flush=True)


RESULT_RANGES = ["B16:B31", "B34:B36", "B39:B51", "D17:F120"]


def clear_results(ws):
    """Blank every result cell so it is obvious which numbers belong to the run in progress."""
    ws.batch_clear(RESULT_RANGES)


def refresh_labels(ws):
    """Rewrite the Pricer tab's column-A labels and notes so label changes in sheet_layout reach existing sheets without --init."""
    cells = [gspread.Cell(row, 1, label) for row, label, *_ in PRICER]
    ws.update_cells(cells, value_input_option="RAW")
    try: ws.insert_notes(NOTES)
    except Exception: pass                      # noqa: notes are cosmetic


def put(ws, first_label, values):
    """Write a list of values down column B starting at a labelled row."""
    r0 = ROW[first_label]
    ws.update(range_name="B%d:B%d" % (r0, r0 + len(values) - 1), values=[[x] for x in values], value_input_option="RAW")


def sync_schedule(sh, mkt, term, freq, rate, notional, preset):
    """Rebuild Schedule rows for (term, freq). Ticks survive unless the preset dropdown changed since the last run."""
    ws = get_ws(sh, "Schedule")
    vals = ws.get_values(value_render_option=UNF)
    key, last = ws.acell(KEY_CELL).value, (ws.acell(PRESET_CELL).value or "")
    ticks = {}
    fresh = key != "%d|%d" % (term, freq) or len(vals) <= 1
    if not fresh:
        col = SCHEDULE_COLUMNS.index("Cancel here?")
        for r in vals[1:]:
            if r and r[0] != "" and len(r) > col:
                ticks[int(float(r[0]))] = (r[col] is True) or str(r[col]).strip().upper() == "TRUE"
    p = preset_ticks(preset, term, freq)
    if p is not None and (preset != last or fresh):
        ticks = {k: (k in p) for k in range(term * 12 // freq)}
    rows, npv = build_schedule(mkt, term, freq, rate, notional, ticks)
    ws.clear()
    ws.update(range_name="A1", values=[SCHEDULE_COLUMNS] + [[r[c] for c in SCHEDULE_COLUMNS] for r in rows], value_input_option="RAW")
    ws.update(range_name=KEY_CELL, values=[["%d|%d" % (term, freq)]]); ws.update(range_name=PRESET_CELL, values=[[preset]])
    if fresh: style_schedule(sh, ws)
    return ws, rows, [r["#"] for r in rows if r["Cancel here?"]], npv


def write_per_date(ws, rows, result, profile=None):
    eur = {k: v for (_, v, _, k) in result["europeans"]}
    cells = []
    for r in rows:
        k = r["#"]
        if k in eur:
            cells.append(gspread.Cell(k + 2, SCHEDULE_COLUMNS.index("European value at this date £") + 1, round(eur[k])))
            cells.append(gspread.Cell(k + 2, SCHEDULE_COLUMNS.index("Normal vol at strike (bp)") + 1, round(result["nvols"][k] * 1e4, 1)))
            if profile: cells.append(gspread.Cell(k + 2, SCHEDULE_COLUMNS.index("Probability cancelled here") + 1, round(profile["by_period"].get(k, 0.0), 4)))
    if cells: ws.update_cells(cells, value_input_option="RAW")


# ---------------------------------------------------------------- the run
def run(sh):
    inp = read_inputs(sh); ws = sh.worksheet("Pricer")
    mkt, asof = read_market(sh, inp["reversion"])
    term, freq, notional = inp["term"], inp["freq"], inp["notional"]
    fair = inp["rate"] == "fair"; K = 0.02 if fair else inp["rate"]
    clear_results(ws); refresh_labels(ws)
    status(sh, "running: building schedule")
    sched_ws, rows, calls, swap_npv = sync_schedule(sh, mkt, term, freq, K, notional, inp["preset"])
    if not calls:
        status(sh, "nothing to price: no dates ticked on Schedule"); return None
    spec = dict(term_years=term, notional=notional, freq_months=freq, call_periods_list=calls)
    if fair:
        status(sh, "running: solving model-fair rate (1 of 3, about a minute)")
        k, r = rate_for_take(mkt, CallableSwap(rate=0.02, **spec), 0.0)
        status(sh, "running: fair %.3f%%, solving dealt rate with collateral (2 of 3)" % (k * 100))
        kc, _ = rate_for_take(mkt, CallableSwap(rate=k, **spec), inp["take_c"])
        status(sh, "running: solving dealt rate without collateral (3 of 3)")
        kn, _ = rate_for_take(mkt, CallableSwap(rate=kc, **spec), inp["take_n"])
        put(ws, "Model-fair rate", [k, kc, kn])
        ws.update(range_name=CELL["Fixed rate we pay"], values=[[k]], value_input_option="RAW")       # 'fair' becomes the solved rate
        K = k
        sched_ws, rows, calls, swap_npv = sync_schedule(sh, mkt, term, freq, K, notional, inp["preset"])
    else:
        status(sh, "running: pricing at %.3f%%" % (K * 100))
        r = price(mkt, CallableSwap(rate=K, **spec))
    s = CallableSwap(rate=K, **spec)
    put(ws, "Priced at", [dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "%04d-%02d-%02d" % (asof.year(), asof.month(), asof.dayOfMonth()),
                          K, r["par"], round(r["cancel_right"]), round(r["coupon_discount"]), round(r["bank_take"]), round(r["intrinsic"]),
                          round(r["best_european"]), r["best_european_expiry"], round(r["time_value"]), round(r["multiple"], 3), r["n_calls"],
                          round(swap_npv), round(r["annuity"] / 100), round(r["calib_err"], 5)])
    ws.update(range_name="D17", values=[[e, round(v), round(i)] for e, v, i, _ in r["europeans"]], value_input_option="RAW")
    profile = None
    if inp["mode"] == "full":
        status(sh, "running: sensitivities (rate, vol, reversion)")
        sen = sensitivities(mkt, s, r)
        status(sh, "running: exercise probabilities and expected life")
        profile = exercise_profile(mkt, s, r)
        status(sh, "running: collateral scenarios")
        col = collateral(mkt, s, r)
        cum = profile["cum_by_year"]
        put(ws, "Bank's take per +10 bp of our rate",
            [round(sen["take_per_10bp_rate"]), round(sen["cancel_per_10bp_vol"]), round(sen["cancel_rev1"]), round(sen["cancel_rev2"]),
             round(profile["expected_life"], 2), round(cum.get(5, 0), 4), round(cum.get(10, 0), 4), round(cum.get(15, 0), 4), round(profile["never"], 4),
             round(col[-50]), round(col[-100]), round(col[-200]), round(col[-300])])
    write_per_date(sched_ws, rows, r, profile)
    return r


def run_job(sh, engine=None):
    """One complete pricing: run, untick Run, write the final status. Used by --once, --watch and the Cloud Run server."""
    ws = sh.worksheet("Pricer"); t = time.time()
    if engine: ws.update(range_name=CELL["Engine"], values=[[engine]])
    try:
        r = run(sh)
        msg = "done in %.0f s: cancel right £%s, multiple %.3f" % (time.time() - t, format(round(r["cancel_right"]), ","), r["multiple"]) if r else "nothing ticked"
    except Exception as e:                       # noqa
        msg = "error: %s" % e; r = None
    ws.update(range_name=CELL["Run"], values=[[False]], value_input_option="RAW"); status(sh, msg)
    return r


# ---------------------------------------------------------------- entry points
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sheet", required=True); ap.add_argument("--key", default="sa-key.json")
    ap.add_argument("--init", action="store_true", help="build or repair the sheet layout"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true"); ap.add_argument("--interval", type=int, default=3)
    a = ap.parse_args(); sh = open_sheet(a.sheet, a.key)
    if a.init:
        init_sheet(sh); print("layout ready: Pricer, Market, Schedule"); return
    ws = sh.worksheet("Pricer")
    if a.once or not a.watch:
        run_job(sh, "Mac, one run"); return
    print("watching '%s' every %ds: tick Pricer!Run (or LOBO > Price now) to price. Ctrl+C to stop." % (sh.title, a.interval))
    last_hb = 0
    try:
        while True:
            if time.time() - last_hb > 30:
                ws.update(range_name=CELL["Engine"], values=[["Mac connected " + dt.datetime.now().strftime("%H:%M:%S")]]); last_hb = time.time()
            if str(ws.acell(CELL["Run"]).value).strip().upper() == "TRUE":
                run_job(sh); last_hb = 0
            time.sleep(a.interval)
    except KeyboardInterrupt:
        ws.update(range_name=CELL["Engine"], values=[["Mac disconnected " + dt.datetime.now().strftime("%H:%M")]])


if __name__ == "__main__":
    main()
