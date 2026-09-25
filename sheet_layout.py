"""Layout of the Google Sheet: three tabs (Pricer, Market, Schedule). `init_sheet` builds or repairs it in place,
carrying over market data and inputs from an older layout if it finds one."""
import gspread
from gspread.utils import ValidationConditionType
from pricer import SCHEDULE_COLUMNS
from pricer.data import LIVE_ASOF, LIVE_CURVE, OFFSETS, LIVE_SURFACE

PRESETS = ["semi-annual 2-15", "annual 2-15", "annual 3-10", "six dates", "single 2y", "full strip", "as ticked on Schedule"]
MODES = ["Quick", "Full"]
MONEY, PCT, PCT0, PCT1 = '"£"#,##0', "0.000%", "0%", "0.0%"
BLUE, GREY, GREEN = {"red": 0.87, "green": 0.92, "blue": 0.98}, {"red": 0.93, "green": 0.93, "blue": 0.93}, {"red": 0.89, "green": 0.96, "blue": 0.89}

# ---- Pricer tab: (row, label, kind, default). kind: h=header, i=input, o=output, m=money, p=percent, b=bool, d=dropdown, t=text
# A label's key is the text before a double space; the bracketed part after it is explanation only.
LAYOUT_VERSION = "v3"
PRICER = [
    (4, "INPUTS", "h"),
    (5, "Swap term (years)", "i", 40), (6, "Fixed rate we pay", "ip", 0.0143), (7, "Coupon frequency (months)", "i", 6),
    (8, "Notional", "im", 10_000_000), (9, "Call dates", "id", "semi-annual 2-15"),
    (10, "Stress: curve shift (bp)", "i", 0), (11, "Stress: vol shift (bp)", "i", 0),
    (12, "Run", "ib", False), (13, "Status", "t", ""), (14, "Engine", "t", ""),
    (16, "RESULTS", "h"),
    (17, "Priced at", "t"), (18, "Market as-of", "t"), (19, "Stress applied", "t"),
    (20, "Fixed rate priced", "p"), (21, "Par swap rate", "p"),
    (22, "Swap value to us", "m"), (23, "Bank's cancel right", "m"), (24, "Bank's take", "m"),
    (25, "Best single-date option  (European)", "m"), (26, "Best single date (years)", "o"),
    (27, "Bermudan time value  (what the other dates add)", "m"), (28, "Multiple of best European", "o"),
    (29, "Expected life (years)", "o"), (30, "Chance cancelled by year 5", "p0"), (31, "Call dates ticked", "o"),
    (32, "Model-fair rate  (when fair is typed)", "p"),
    (34, "INVESTOR RETURN  (net spread over SONIA in bp, after the premium paid for the loan, for the years the swap runs)", "h"),
    (35, "Years of annuity to each horizon", "t"),
    (36, "LOBO coupon", "t"),
    (44, "ADVANCED  (click + in the left margin to expand)", "h"),
    (45, "Run mode", "id", "Quick"),
    (46, "Dealt rate, collateral", "p"), (47, "Dealt rate, no collateral", "p"),
    (48, "Bank's take per +10 bp of our rate", "m"), (49, "Cancel right per +10 bp of normal vol", "m"),
    (50, "Cancel right at 1% reversion", "m"), (51, "Cancel right at 2% reversion", "m"),
    (52, "Chance cancelled by year 10", "p0"), (53, "Chance cancelled by year 15", "p0"), (54, "Chance never cancelled", "p0"),
    (55, "Investor posts if rates -50 bp", "m"), (56, "Investor posts if rates -100 bp", "m"),
    (57, "Investor posts if rates -200 bp", "m"), (58, "Investor posts if rates -300 bp", "m"),
    (59, "Intrinsic on the best single date", "m"), (60, "Annuity per 1%", "m"),
    (61, "Swap value from Schedule cashflows  (check)", "m"), (62, "Calibration error (max, relative)", "o"),
    (63, "Mean reversion", "ip", 0.03), (64, "Bank take, collateral", "im", 150_000), (65, "Bank take, no collateral", "im", 350_000),
]
ROW = {label.split("  (")[0]: row for row, label, *_ in PRICER}
CELL = {k: "B%d" % ROW[k] for k in ROW}
ADVANCED_ROWS = (45, 65)                 # collapsed row group (inclusive)
RET_HEAD, RET_ROWS = 36, (37, 42)        # investor return table: header row, first and last data rows
RET_LOANS = [(0.045, 1), (0.0475, 2), (0.05, 2), (0.05, 3), (0.055, 2), (0.055, 3)]
RET_HORIZONS = ["5 years", "10 years", "15 years", "Full term"]      # after the expected-life column
LADDER_COL = "I"                         # European ladder in I:K from row 16
VERSION_CELL, CLEAR_CELL = "Z1", "Z3"    # on Pricer: layout version; the result ranges the button clears (read by apps_script.gs)
RESULT_RANGES = ["B17:B32", "B46:B62", "C35:G35", "I18:K120"]
KEY_CELL, PRESET_CELL = "Z1", "Z2"       # on Schedule: 'term|freq' of the current rows, last preset applied
NOTES = {
    "B6": "A rate like 1.43%, or the word fair: the script then solves the rate at which the bank's take is zero (about 2 minutes) and writes it here.",
    "B9": "Preset call dates, applied to the Schedule tab on the next run. Choose 'as ticked on Schedule' to tick dates yourself.",
    "B10": "Stress test: moves every SONIA rate by this many bp before pricing (e.g. -100). Results then show the stressed world. 0 = today's market.",
    "B11": "Stress test: moves every swaption normal vol by this many bp before pricing (e.g. +20). 0 = today's market.",
    "B12": "Tick to price (or LOBO menu > Price now). Results are cleared, then refilled in about 15 seconds.",
    "B14": "Who last priced: the Cloud Run service (from the button) or a Mac running the watcher.",
    "B22": "What paying our fixed rate instead of the par rate is worth to us over the full term, on today's curve. Certain, no model.",
    "B23": "What the bank's right to cancel is worth on the model. This is what the bank is paying for with the low fixed rate.",
    "B24": "Cancel right minus swap value: what the bank keeps at this fixed rate. Zero at the model-fair rate. Negative means the bank is overpaying.",
    "B25": "The most valuable single cancel date on its own: a plain European swaption, market vols, no model judgement. A floor for what the bank should pay.",
    "B28": "Cancel right divided by the best European. About 1.10 on our model, 1.06-1.07 on a bank's usual settings, 1.00 means the bank only paid for one date.",
    "B29": "Model's expected time until the bank cancels (full term if never). Drives the return table's first column.",
    "A34": "Net spread = LOBO coupon - fixed rate priced - premium spread over the horizon. Edit coupons and premiums; the cells update without a rerun.",
    "A35": "How many years of 1% a point of premium is spread over. 1 point over 5 years costs about 22 bp a year; over 40 years about 6 bp.",
    "B48": "How much more the bank keeps if our fixed rate is 10 bp higher. Small because the option is deep in the money, which is why bank charges matter so much in rate terms.",
    "B55": "Mark-to-market the investor would post to the bank today under a CSA if the whole curve moved by this much.",
    "B63": "Model judgement, not market data. 3% is our setting; a bank buying the option will show 1-2%, which lowers the cancel right and raises the fair rate.",
}

MARKET_ASOF, CURVE_HEAD, VOL_HEAD = "B1", 4, 4     # Market!B1 as-of; curve header row 4 (A:B); vol header row 4 (D onwards)


def col_letter(n):
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s


def _fmt(pattern=None, bold=False, bg=None, size=None, halign=None):
    f = {}
    if pattern: f["numberFormat"] = {"type": "NUMBER", "pattern": pattern}
    if bold or size: f["textFormat"] = {"bold": bold, **({"fontSize": size} if size else {})}
    if bg: f["backgroundColor"] = bg
    if halign: f["horizontalAlignment"] = halign
    return f


def _widths(sh, ws, widths):
    reqs = [{"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                           "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in widths.items()]
    sh.batch_update({"requests": reqs})


def get_ws(sh, name, rows=200, cols=30):
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(name, rows, cols)


def _old_kv(sh, name):
    try:
        return {r[0].strip(): (r[1] if len(r) > 1 else "") for r in sh.worksheet(name).get_all_values() if r and r[0]}
    except gspread.WorksheetNotFound:
        return {}


def _num(v, default):
    try:
        return float(str(v).replace(",", "").replace("%", ""))
    except ValueError:
        return default


CARRY = {"Swap term (years)": ["Term (years)"], "Fixed rate we pay": ["Fixed rate %"], "Coupon frequency (months)": ["Frequency (months)"],
         "Mean reversion": [], "Bank take, collateral": ["Bank take, collateral £"], "Bank take, no collateral": ["Bank take, no collateral £"],
         "Notional": [], "Call dates": [], "Run mode": [], "Stress: curve shift (bp)": [], "Stress: vol shift (bp)": []}


def _carried(key, old):
    """Value for an input from an older layout (same label, or a listed older label; '%'-labelled rates were in percent units)."""
    for lab in [key] + CARRY.get(key, []):
        if lab in old and str(old[lab]).strip() != "":
            v = old[lab]
            if str(v).strip().lower() in ("fair", "solve"): return "fair"
            return _num(v, None) * (0.01 if lab.endswith("%") else 1) if _num(v, None) is not None else v
    return None


def init_pricer(sh, old):
    """(Re)build the Pricer tab. `old` maps labels to values from whatever layout was there before (inputs are carried over)."""
    ws = get_ws(sh, "Pricer", 80, 16)
    ws.clear()
    cells, fmts = [], []
    cells.append(gspread.Cell(1, 1, "LOBO cancellable swap pricer"))
    cells.append(gspread.Cell(2, 1, "Fill the blue cells, then LOBO menu > Price now (or tick Run). Results appear in about 15 seconds. Hover a cell for an explanation."))
    fmts += [{"range": "A1", "format": _fmt(bold=True, size=14)}, {"range": "A2", "format": {"textFormat": {"italic": True}}}]
    for row, label, kind, *dflt in PRICER:
        cells.append(gspread.Cell(row, 1, label))
        if kind == "h":
            fmts.append({"range": "A%d:K%d" % (row, row), "format": _fmt(bold=True, bg=GREY)}); continue
        if dflt:
            v = _carried(label.split("  (")[0], old)
            if v is None or isinstance(v, str) and kind != "id" and v != "fair": v = dflt[0]
            cells.append(gspread.Cell(row, 2, v))
        f = {}
        if kind.startswith("i"): f.update(_fmt(bg=BLUE))
        pat = {"m": MONEY, "p": PCT, "p0": PCT0}.get(kind.lstrip("i"))
        if pat: f.update(_fmt(pat))
        if kind.endswith("o"): f.update(_fmt("0.00"))
        if f: fmts.append({"range": "B%d" % row, "format": f})
    # investor return table
    r0, r1 = RET_ROWS
    cells += [gspread.Cell(RET_HEAD, 2, "Premium paid (pts)"), gspread.Cell(RET_HEAD, 3, "Expected life")]
    for j, h in enumerate(RET_HORIZONS): cells.append(gspread.Cell(RET_HEAD, 4 + j, h))
    for i, (c, p) in enumerate(RET_LOANS):
        cells += [gspread.Cell(r0 + i, 1, c), gspread.Cell(r0 + i, 2, p)]
    fmts += [{"range": "A%d:G%d" % (RET_HEAD, RET_HEAD), "format": _fmt(bold=True, halign="CENTER")},
             {"range": "A%d:A%d" % (r0, r1), "format": _fmt(PCT, bg=BLUE)}, {"range": "B%d:B%d" % (r0, r1), "format": _fmt("0.0", bg=BLUE)},
             {"range": "C%d:G%d" % (r0, r1), "format": _fmt("0;[Red]-0", halign="CENTER")},
             {"range": "A35:G35", "format": {"textFormat": {"italic": True, "foregroundColor": {"red": 0.5, "green": 0.5, "blue": 0.5}}, "numberFormat": {"type": "NUMBER", "pattern": "0.0"}}}]
    # European ladder
    L = LADDER_COL
    cells += [gspread.Cell(16, 9, "EUROPEAN LADDER  (each ticked date on its own)"), gspread.Cell(17, 9, "Date (years)"), gspread.Cell(17, 10, "Option value"), gspread.Cell(17, 11, "Forward swap value")]
    fmts += [{"range": "I17:K17", "format": _fmt(bold=True)}, {"range": "J18:K120", "format": _fmt(MONEY)}]
    ws.update_cells(cells, value_input_option="RAW")
    write_return_formulas(ws)
    ws.batch_format(fmts)
    ws.add_validation(CELL["Run"], ValidationConditionType.boolean, [], strict=True)
    ws.add_validation(CELL["Call dates"], ValidationConditionType.one_of_list, PRESETS, strict=True, showCustomUi=True)
    ws.add_validation(CELL["Run mode"], ValidationConditionType.one_of_list, MODES, strict=True, showCustomUi=True)
    ws.insert_notes(NOTES)
    ws.freeze(rows=2)
    _widths(sh, ws, {0: 300, 1: 130, 2: 95, 3: 95, 4: 95, 5: 95, 6: 95, 7: 20, 8: 100, 9: 120, 10: 130})
    ws.update(range_name=VERSION_CELL, values=[[LAYOUT_VERSION]]); ws.update(range_name=CLEAR_CELL, values=[[",".join(RESULT_RANGES)]]); ws.hide_columns(25, 26)
    collapse_advanced(sh, ws)
    return ws


def write_return_formulas(ws):
    """The return table's live formulas: net spread bp = (coupon - rate priced) x 10000 - premium pts / annuity years x 100."""
    r0, r1 = RET_ROWS
    head = ['="Expected life ("&TEXT($B$%d,"0.0")&"y)"' % ROW["Expected life (years)"]]
    rows = [head]
    for r in range(r0, r1 + 1):
        rows.append(['=IF(OR($A%d="",C$35=""),"",ROUND(($A%d-$B$%d)*10000-$B%d/C$35*100,0))' % (r, r, ROW["Fixed rate priced"], r)])
    ws.update(range_name="C%d:C%d" % (RET_HEAD, r1), values=rows, value_input_option="USER_ENTERED")
    body = []
    for r in range(r0, r1 + 1):
        body.append(['=IF(OR($A%d="",%s$35=""),"",ROUND(($A%d-$B$%d)*10000-$B%d/%s$35*100,0))' % (r, c, r, ROW["Fixed rate priced"], r, c) for c in "DEFG"])
    ws.update(range_name="D%d:G%d" % (r0, r1), values=body, value_input_option="USER_ENTERED")


def collapse_advanced(sh, ws):
    a, b = ADVANCED_ROWS
    rng = {"sheetId": ws.id, "dimension": "ROWS", "startIndex": a - 1, "endIndex": b}
    try:
        sh.batch_update({"requests": [{"deleteDimensionGroup": {"range": rng}}]})
    except Exception:
        pass                                                       # noqa: no group yet
    sh.batch_update({"requests": [{"addDimensionGroup": {"range": rng}},
                                  {"updateDimensionGroup": {"dimensionGroup": {"range": rng, "depth": 1, "collapsed": True}, "fields": "collapsed"}}]})


def ensure_layout(sh):
    """Bring an existing sheet's Pricer tab up to the current layout, keeping its inputs. No-op when already current."""
    ws = get_ws(sh, "Pricer", 80, 16)
    if ws.acell(VERSION_CELL).value == LAYOUT_VERSION:
        return False
    old = {}
    for name in ("Settings", "Structure"): old.update(_old_kv(sh, name))
    try:
        for r in ws.get_values(value_render_option="UNFORMATTED_VALUE"):
            if r and str(r[0]).strip() and len(r) > 1 and r[1] != "": old[str(r[0]).split("  (")[0].strip()] = r[1]
    except Exception:
        pass                                                       # noqa
    init_pricer(sh, old)
    return True


def init_market(sh, old_curve, old_vols, old_asof):
    ws = get_ws(sh, "Market", 120, 30)
    ws.clear()
    asof = old_asof or "%04d-%02d-%02d" % (LIVE_ASOF.year(), LIVE_ASOF.month(), LIVE_ASOF.dayOfMonth())
    curve = old_curve or [[t, r / 100] for t, r in LIVE_CURVE]
    if old_vols:
        head, rows = old_vols[0], old_vols[1:]
    else:
        head = ["Expiry (y)", "Tenor (y)", "ATM strike", *OFFSETS]
        rows = [[e, t, atm / 100, *[v.get(o, "") for o in OFFSETS]] for e, t, atm, v in LIVE_SURFACE]
    vals = [["As-of date", asof, "", "Paste new market data over these blocks; keep the header rows. Rates and strikes are percent cells, vols are normal vols in bp."],
            [], ["SONIA OIS CURVE", "", "", "SWAPTION NORMAL VOLS (bp) BY OFFSET FROM ATM (bp)"],
            ["Tenor", "Rate", "", *head]]
    n = max(len(curve), len(rows))
    for i in range(n):
        vals.append([*(curve[i] if i < len(curve) else ["", ""]), "", *(rows[i] if i < len(rows) else [])])
    ws.update(range_name="A1", values=vals, value_input_option="RAW")
    ws.format("A1", _fmt(bold=True)); ws.format("B1", _fmt(bg=BLUE, halign="LEFT"))
    ws.batch_format([{"range": "A3:B3", "format": _fmt(bold=True, bg=GREY)}, {"range": "D3:%s3" % col_letter(3 + len(head)), "format": _fmt(bold=True, bg=GREY)},
                     {"range": "A4:B4", "format": _fmt(bold=True)}, {"range": "D4:%s4" % col_letter(3 + len(head)), "format": _fmt(bold=True)},
                     {"range": "B5:B%d" % (4 + len(curve)), "format": _fmt(PCT, bg=BLUE)}, {"range": "A5:A%d" % (4 + len(curve)), "format": _fmt(bg=BLUE)},
                     {"range": "F5:F%d" % (4 + len(rows)), "format": _fmt(PCT, bg=BLUE)},
                     {"range": "D5:E%d" % (4 + len(rows)), "format": _fmt(bg=BLUE)}, {"range": "G5:%s%d" % (col_letter(3 + len(head)), 4 + len(rows)), "format": _fmt("0.00", bg=BLUE)}])
    ws.freeze(rows=4)
    _widths(sh, ws, {0: 90, 1: 90, 2: 20, 3: 80, 4: 80, 5: 90, **{i: 62 for i in range(6, 4 + len(head))}})
    return ws


def init_schedule(sh):
    ws = get_ws(sh, "Schedule", 200, 30)
    ws.clear()
    ws.update(range_name="A1", values=[SCHEDULE_COLUMNS], value_input_option="RAW")
    ws.update(range_name=KEY_CELL, values=[[""]]); ws.update(range_name=PRESET_CELL, values=[[""]])
    style_schedule(sh, ws)
    return ws


def style_schedule(sh, ws):
    c = {name: col_letter(i + 1) for i, name in enumerate(SCHEDULE_COLUMNS)}
    money = ["Fixed cashflow £", "Projected SONIA cashflow £", "Net cashflow £", "PV of net £", "Remaining annuity £ per 1%", "Intrinsic if cancelled here £", "European value at this date £"]
    fm = [{"range": "A1:%s1" % col_letter(len(SCHEDULE_COLUMNS)), "format": _fmt(bold=True, bg=GREY)}]
    fm += [{"range": "%s2:%s200" % (c[m], c[m]), "format": _fmt(MONEY)} for m in money]
    fm += [{"range": "%s2:%s200" % (c["Discount factor"], c["Discount factor"]), "format": _fmt("0.000000")},
           {"range": "%s2:%s200" % (c["Accrual (y)"], c["Accrual (y)"]), "format": _fmt("0.0000")},
           {"range": "%s2:%s200" % (c["Forward swap rate from here"], c["Forward swap rate from here"]), "format": _fmt(PCT)},
           {"range": "%s2:%s200" % (c["Strike - forward (bp)"], c["Strike - forward (bp)"]), "format": _fmt("0.0")},
           {"range": "%s2:%s200" % (c["Normal vol at strike (bp)"], c["Normal vol at strike (bp)"]), "format": _fmt("0.0")},
           {"range": "%s2:%s200" % (c["Probability cancelled here"], c["Probability cancelled here"]), "format": _fmt(PCT1)},
           {"range": "%s2:%s200" % (c["Cancel here?"], c["Cancel here?"]), "format": _fmt(bg=BLUE, halign="CENTER")}]
    ws.batch_format(fm)
    ws.add_validation("%s2:%s200" % (c["Cancel here?"], c["Cancel here?"]), ValidationConditionType.boolean, [], strict=True)
    ws.freeze(rows=1, cols=4)
    _widths(sh, ws, {i: 105 for i in range(len(SCHEDULE_COLUMNS))})
    ws.hide_columns(25, 26)


OLD_TABS = ["Start here", "Curve", "Vols", "Settings", "Structure", "Results", "Portfolio", "Collateral"]


def init_sheet(sh):
    """Build the three-tab layout in `sh`, migrating an older multi-tab layout if present. Idempotent."""
    old_set, old_struct = _old_kv(sh, "Settings"), _old_kv(sh, "Structure")
    old_curve, old_vols = [], []
    try:
        old_curve = [[r[0], _num(r[1], 0) / 100] for r in sh.worksheet("Curve").get_all_values()[1:] if r and r[0] and r[1]]
    except gspread.WorksheetNotFound:
        pass
    try:
        vr = sh.worksheet("Vols").get_all_values()
        offs = [int(_num(x, 0)) for x in vr[0][3:] if x != ""]
        old_vols = [["Expiry (y)", "Tenor (y)", "ATM strike", *offs]] + [[_num(r[0], 0), _num(r[1], 0), _num(r[2], 0) / 100, *[_num(x, "") if x != "" else "" for x in r[3:3 + len(offs)]]]
                                                                        for r in vr[1:] if r and r[0] and r[1]]
    except gspread.WorksheetNotFound:
        pass
    existing = {w.title for w in sh.worksheets()}
    init_pricer(sh, {**old_set, **old_struct})
    init_market(sh, old_curve, old_vols, old_set.get("As-of date", ""))
    init_schedule(sh)
    for name in OLD_TABS:
        if name in existing:
            sh.del_worksheet(sh.worksheet(name))
    sh.reorder_worksheets([sh.worksheet(n) for n in ("Pricer", "Market", "Schedule")])
