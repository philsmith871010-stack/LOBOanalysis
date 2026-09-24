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
PRICER = [
    (4, "INPUTS", "h"),
    (5, "Term (years)", "i", 40), (6, "Fixed rate we pay", "ip", 0.0143), (7, "Coupon frequency (months)", "i", 6),
    (8, "Notional", "im", 10_000_000), (9, "Call dates", "id", "semi-annual 2-15"), (10, "Run mode", "id", "Quick"),
    (11, "Run", "ib", False), (12, "Status", "t", ""), (13, "Mac watcher", "t", ""),
    (15, "RESULTS", "h"),
    (16, "Priced at", "t"), (17, "Market as-of", "t"), (18, "Fixed rate priced", "p"), (19, "Par swap rate", "p"),
    (20, "Cancel right, value to bank", "m"), (21, "Coupon discount, value to us", "m"), (22, "Bank's take", "m"),
    (23, "Intrinsic, best single date", "m"), (24, "Best European", "m"), (25, "Best European expiry (y)", "o"),
    (26, "Bermudan time value", "m"), (27, "Multiple of best European", "o"), (28, "Call dates ticked", "o"),
    (29, "Swap value to us (Schedule PV)", "m"), (30, "Annuity per 1%", "m"), (31, "Calibration error (max, relative)", "o"),
    (33, "FAIR RATE  (type fair in B6)", "h"),
    (34, "Model-fair rate", "p"), (35, "Dealt rate, collateral", "p"), (36, "Dealt rate, no collateral", "p"),
    (38, "FULL RUN  (Run mode = Full)", "h"),
    (39, "Bank's take per +10 bp of our rate", "m"), (40, "Cancel right per +10 bp of normal vol", "m"),
    (41, "Cancel right at 2% reversion", "m"), (42, "Cancel right at 4% reversion", "m"),
    (43, "Expected life (y)", "o"), (44, "Probability cancelled by year 5", "p0"), (45, "Probability cancelled by year 10", "p0"),
    (46, "Probability cancelled by year 15", "p0"), (47, "Probability never cancelled", "p0"),
    (48, "Investor posts if rates -50 bp", "m"), (49, "Investor posts if rates -100 bp", "m"),
    (50, "Investor posts if rates -200 bp", "m"), (51, "Investor posts if rates -300 bp", "m"),
    (53, "ASSUMPTIONS", "h"),
    (54, "Mean reversion", "ip", 0.03), (55, "Bank take, collateral", "im", 150_000), (56, "Bank take, no collateral", "im", 350_000),
    (57, "bp of spread per premium point", "i", 23), (58, "Investor minimum spread bp", "i", 250), (59, "Investor target spread bp", "i", 300),
]
ROW = {label.split("  (")[0]: row for row, label, *_ in PRICER}
CELL = {k: "B%d" % ROW[k] for k in ROW}
NOTES = {
    "B6": "A rate like 1.43%, or the word fair: then the script solves the model-fair rate and the two dealt rates (about 2 minutes).",
    "B9": "Preset call dates, applied to the Schedule tab on the next run. Choose 'as ticked on Schedule' to tick dates yourself.",
    "B10": "Quick (about 10 s): price, European ladder, multiple. Full (about 1 min): adds sensitivities, exercise probabilities, expected life and collateral scenarios.",
    "B11": "Tick to price. The Mac watcher picks it up within a few seconds and unticks it when done. Or use the LOBO menu / button.",
    "B13": "The Mac script writes the time here every 30 s while it is watching. If this is old, nothing will price.",
    "B22": "Cancel right minus coupon discount: what the bank keeps on the model. Zero at the model-fair rate.",
    "B27": "Cancel right / best European. About 1.10 is model-fair; 1.07 is a good print; 1.00 means the bank only paid for one date.",
    "B39": "How much more the bank keeps if our fixed rate is 10 bp higher. Small because the option is deep in the money.",
    "B48": "Mark-to-market the investor would post to the bank today under a CSA if the whole curve moved by this much.",
}
PORTFOLIO_LOANS = [(40, 0.04, 1), (40, 0.0425, 1), (40, 0.045, 2), (40, 0.0475, 2), (40, 0.05, 2), (40, 0.055, 3),
                   (50, 0.045, 2), (50, 0.0475, 2), (50, 0.05, 3), (50, 0.055, 3), (30, 0.05, 1), (30, 0.055, 2)]
LADDER_COL, PORT_COL = "D", "H"          # European ladder in D:F, portfolio in H:N, both from row 15
KEY_CELL, PRESET_CELL = "Z1", "Z2"       # on Schedule: 'term|freq' of the current rows, last preset applied

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


def init_pricer(sh, old_struct, old_set):
    ws = get_ws(sh, "Pricer", 80, 16)
    ws.clear()
    cells, fmts = [], []
    cells.append(gspread.Cell(1, 1, "LOBO cancellable swap pricer"))
    cells.append(gspread.Cell(2, 1, "Fill the blue cells, tick Run (or LOBO menu > Price now). The Mac watcher prices within a few seconds and fills the results. Hover a cell for notes."))
    fmts += [{"range": "A1", "format": _fmt(bold=True, size=14)}, {"range": "A2", "format": {"textFormat": {"italic": True}}}]
    carry = {"Term (years)": ("Term (years)", 1), "Fixed rate we pay": ("Fixed rate %", 0.01), "Coupon frequency (months)": ("Frequency (months)", 1),
             "Notional": ("Notional", 1), "Mean reversion": ("Mean reversion", 1), "Bank take, collateral": ("Bank take, collateral £", 1),
             "Bank take, no collateral": ("Bank take, no collateral £", 1), "bp of spread per premium point": ("bp of spread per premium point", 1),
             "Investor minimum spread bp": ("Investor minimum spread bp", 1), "Investor target spread bp": ("Investor target spread bp", 1)}
    old = {**old_set, **old_struct}
    for row, label, kind, *dflt in PRICER:
        cells.append(gspread.Cell(row, 1, label))
        if kind == "h":
            fmts.append({"range": "A%d:B%d" % (row, row), "format": _fmt(bold=True, bg=GREY)}); continue
        if dflt:
            v = dflt[0]; key = label.split("  (")[0]
            if key in carry and carry[key][0] in old and str(old[carry[key][0]]).strip() != "":
                ov = old[carry[key][0]]
                v = "fair" if str(ov).strip().lower() in ("fair", "solve") else _num(ov, v) * carry[key][1]
            cells.append(gspread.Cell(row, 2, v))
        f = {}
        if kind.startswith("i"): f.update(_fmt(bg=BLUE))
        pat = {"m": MONEY, "p": PCT, "p0": PCT0}.get(kind.lstrip("i"))
        if pat: f.update(_fmt(pat))
        if kind.endswith("o"): f.update(_fmt("0.000"))
        if f: fmts.append({"range": "B%d" % row, "format": f})
    # European ladder + portfolio blocks
    L, P = LADDER_COL, PORT_COL
    cells += [gspread.Cell(15, 4, "EUROPEAN LADDER  (each ticked date on its own)"), gspread.Cell(16, 4, "Expiry (y)"), gspread.Cell(16, 5, "Value"), gspread.Cell(16, 6, "Forward swap")]
    cells += [gspread.Cell(15, 8, "PORTFOLIO  (spread on each LOBO at the fixed rate priced, B18)")]
    for j, h in enumerate(["LOBO term (y)", "Coupon", "Premium (pts)", "Dealt rate", "Gross spread bp", "Net spread bp", "Verdict"]):
        cells.append(gspread.Cell(16, 8 + j, h))
    fmts += [{"range": "D15:F15", "format": _fmt(bold=True, bg=GREY)}, {"range": "D16:F16", "format": _fmt(bold=True)},
             {"range": "H15:N15", "format": _fmt(bold=True, bg=GREY)}, {"range": "H16:N16", "format": _fmt(bold=True)},
             {"range": "E17:F80", "format": _fmt(MONEY)}, {"range": "I17:I40", "format": _fmt(PCT, bg=BLUE)}, {"range": "J17:J40", "format": _fmt(bg=BLUE)},
             {"range": "K17:K40", "format": _fmt(PCT)}, {"range": "H17:H40", "format": _fmt(bg=BLUE)}]
    ws.update_cells(cells, value_input_option="RAW")
    formulas = []
    for i, (T, c, pts) in enumerate(PORTFOLIO_LOANS, 17):
        formulas.append([T, c, pts, "=$B$18", "=ROUND((I%d-K%d)*10000,0)" % (i, i), "=L%d-$B$57*J%d" % (i, i),
                         '=IF(M%d>=$B$59,"target",IF(M%d>=$B$58,"minimum","out"))' % (i, i)])
    ws.update(range_name="H17:N%d" % (16 + len(PORTFOLIO_LOANS)), values=formulas, value_input_option="USER_ENTERED")
    ws.batch_format(fmts)
    ws.add_validation(CELL["Run"], ValidationConditionType.boolean, [], strict=True)
    ws.add_validation(CELL["Call dates"], ValidationConditionType.one_of_list, PRESETS, strict=True, showCustomUi=True)
    ws.add_validation(CELL["Run mode"], ValidationConditionType.one_of_list, MODES, strict=True, showCustomUi=True)
    ws.insert_notes(NOTES)
    ws.freeze(rows=2)
    _widths(sh, ws, {0: 290, 1: 150, 2: 30, 3: 90, 4: 110, 5: 110, 6: 30, 7: 100, 8: 80, 9: 100, 10: 90, 11: 110, 12: 110, 13: 80})
    return ws


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
    init_pricer(sh, old_struct, old_set)
    init_market(sh, old_curve, old_vols, old_set.get("As-of date", ""))
    init_schedule(sh)
    for name in OLD_TABS:
        if name in existing:
            sh.del_worksheet(sh.worksheet(name))
    sh.reorder_worksheets([sh.worksheet(n) for n in ("Pricer", "Market", "Schedule")])
