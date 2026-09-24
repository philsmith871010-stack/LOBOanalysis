"""Builds LOBO_pricer_template.xlsx — the sheet layout price_sheet.py expects, pre-filled with the live data set."""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from pricer.data import LIVE_CURVE, OFFSETS, _ROWS
wb = Workbook(); H = Font(bold=True, color="FFFFFF"); HF = PatternFill("solid", fgColor="1F3864"); B = Font(bold=True); IN = PatternFill("solid", fgColor="FFF2CC")
def head(ws, row, vals):
    for i, v in enumerate(vals, 1):
        c = ws.cell(row=row, column=i, value=v); c.font = H; c.fill = HF
ws = wb.active; ws.title = "Curve"; head(ws, 1, ["Tenor", "Rate %"])
for i, (t, r) in enumerate(LIVE_CURVE, 2): ws.cell(row=i, column=1, value=t); ws.cell(row=i, column=2, value=r).fill = IN
ws["D1"] = "Paste the SONIA OIS par rates here (tenor like 10Y, rate in %). Rows can be added; keep the header."
ws = wb.create_sheet("Vols"); head(ws, 1, ["Expiry (y)", "Tenor (y)", "ATM strike %"] + OFFSETS)
for i, (e, t, atm, v) in enumerate(_ROWS, 2):
    ws.cell(row=i, column=1, value=e); ws.cell(row=i, column=2, value=t); ws.cell(row=i, column=3, value=atm)
    for j, x in enumerate(v, 4): ws.cell(row=i, column=j, value=x).fill = IN
ws.cell(row=len(_ROWS) + 3, column=1, value="Normal vols in bp by offset from ATM (header row = offset in bp; any column order). Paste the screen grid row by row.")
ws = wb.create_sheet("Settings")
rows = [("As-of date", "2026-09-22"), ("Notional", 10000000), ("Mean reversion", 0.03), ("Bank take, collateral £", 150000), ("Bank take, no collateral £", 350000),
        ("bp of spread per premium point", 23), ("Investor minimum spread bp", 250), ("Investor target spread bp", 300), ("Run", "FALSE"), ("Status", ""), ("", ""),
        ("Notes", "Set Run to TRUE to price (when price_sheet.py --watch is running on the Mac). Status shows the last run.")]
for i, (k, v) in enumerate(rows, 1):
    ws.cell(row=i, column=1, value=k).font = B; c = ws.cell(row=i, column=2, value=v)
    if k and k not in ("Status", "Notes"): c.fill = IN
ws = wb.create_sheet("Structure")
rows = [("Term (years)", 40), ("Fixed rate %", 1.43), ("Frequency (months)", 6), ("Preset", ""), ("", ""),
        ("Notes", "Fixed rate: a number, or 'fair' to solve the model-fair rate and the dealt rates at the two take levels. The call schedule is whatever is ticked on the Schedule tab. Preset fills the ticks on the next run (semi-annual 2-15, annual 2-15, annual 3-10, six dates, single 2y, full strip, none) and is then cleared.")]
for i, (k, v) in enumerate(rows, 1):
    ws.cell(row=i, column=1, value=k).font = B; c = ws.cell(row=i, column=2, value=v)
    if k and k != "Notes": c.fill = IN
ws = wb.create_sheet("Results")
res = [("Priced at", "reference run 2026-09-22 (live data, 40y, semi-annual 2-15, at model-fair 1.10%)"), ("Market as-of", "2026-09-22"), ("Structure", "40y, calls 2-15y every 6m"),
       ("Model-fair rate %", 1.10), ("Dealt rate, collateral %", 1.43), ("Dealt rate, no collateral %", 1.85), ("Fixed rate priced %", 1.10), ("Par swap rate %", 4.905),
       ("Annuity £ per 1%", 1737393), ("Cancel right, value to bank £", 6612323), ("Coupon discount, value to us £", 6610459), ("Bank's take £", 1864),
       ("Intrinsic (forward swap) £", 5951713), ("Best European £", 6001490), ("Best European expiry (y)", 2.0), ("Bermudan time value £", 610832),
       ("Multiple of best European", 1.102), ("£ per 10 bp of rate", 44000), ("Calibration error (max, relative)", 0.0054), ("Call dates", 27)]
for i, (k, v) in enumerate(res, 1): ws.cell(row=i, column=1, value=k).font = B; ws.cell(row=i, column=2, value=v)
ws["E1"] = "European ladder"; ws["E1"].font = B
for j, v in enumerate(["Expiry (y)", "Value £", "Forward swap £"], 5):
    c = ws.cell(row=2, column=j, value=v); c.font = H; c.fill = HF
for i, (e, v, f) in enumerate([(2.0, 6001490, 5951713)], 3):
    ws.cell(row=i, column=5, value=e); ws.cell(row=i, column=6, value=v); ws.cell(row=i, column=7, value=f)
ws["E5"] = "(reference values; the script rewrites this block on every run)"
ws = wb.create_sheet("Portfolio"); head(ws, 1, ["LOBO term (y)", "Coupon %", "Premium (pts)", "Dealt rate % used", "Gross spread bp", "Net spread bp", "Verdict"])
loans = [(40, 4.0, 1), (40, 4.25, 1), (40, 4.5, 2), (40, 4.75, 2), (40, 5.0, 2), (40, 5.5, 3), (50, 4.5, 2), (50, 4.75, 2), (50, 5.0, 3), (50, 5.5, 3), (30, 5.0, 1), (30, 5.5, 2)]
for i, (T, c, pts) in enumerate(loans, 2):
    ws.cell(row=i, column=1, value=T); ws.cell(row=i, column=2, value=c).fill = IN; ws.cell(row=i, column=3, value=pts).fill = IN
    ws.cell(row=i, column=4, value='=INDEX(Results!$B:$B,MATCH("Fixed rate priced %",Results!$A:$A,0))'); ws.cell(row=i, column=5, value="=ROUND((B%d-D%d)*100,0)" % (i, i)); ws.cell(row=i, column=6, value="=E%d-Settings!$B$6*C%d" % (i, i))
    ws.cell(row=i, column=7, value='=IF(F%d>=Settings!$B$8,"target",IF(F%d>=Settings!$B$7,"minimum","out"))' % (i, i))
ws["I1"] = "Uses the fixed rate priced on the Structure tab (looked up by label on Results). For a different term, re-price with that term."
ws = wb.create_sheet("Collateral"); head(ws, 1, ["Rates move (parallel)", "Investor posts £", "% of notional"])
for i, (m, v, p) in enumerate([("+50 / +100 bp", 0, 0), ("-25 bp", 160000, 1.6), ("-50 bp", 340000, 3.4), ("-100 bp", 750000, 7.5), ("-150 bp", 1260000, 12.6), ("-200 bp", 1890000, 18.9), ("-300 bp", 3650000, 36.5)], 2):
    ws.cell(row=i, column=1, value=m); ws.cell(row=i, column=2, value=v); ws.cell(row=i, column=3, value=p)
head(ws, 11, ["Year", "Swap still alive", "Average posting £", "95th percentile £", "99th percentile £"])
for i, r in enumerate([(2, "100%", 800000, 3900000, 7800000), (3, "41%", 800000, 4300000, 9300000), (5, "27%", 700000, 4200000, 10100000), (7, "19%", 600000, 3700000, 10600000), (10, "13%", 400000, 2300000, 9200000), (15, "5%", 200000, 0, 5000000)], 12):
    for j, v in enumerate(r, 1): ws.cell(row=i, column=j, value=v)
ws["G1"] = "Reference: 40y at 1.43%, semi-annual 2-15, £10m, live data 2026-09-22 (from the briefing). Not recomputed by the slim script."
for w in wb.worksheets:
    for col in range(1, 25): w.column_dimensions[get_column_letter(col)].width = 14 if col > 1 else 30

# ---- Schedule tab, populated from the pricer with the semi-annual 2-15 ticks ----
from pricer import Market, build_schedule, preset_ticks, SCHEDULE_COLUMNS
from pricer.data import LIVE_ASOF, LIVE_SURFACE
mkt = Market(LIVE_ASOF, LIVE_CURVE, LIVE_SURFACE)
ticks = {k: (k in preset_ticks("semi-annual 2-15", 40, 6)) for k in range(80)}
rows, npv = build_schedule(mkt, 40, 6, 0.0143, 10e6, ticks)
ws = wb.create_sheet("Schedule", 4); head(ws, 1, SCHEDULE_COLUMNS)
for i, r in enumerate(rows, 2):
    for j, c in enumerate(SCHEDULE_COLUMNS, 1):
        v = r[c]; cell = ws.cell(row=i, column=j, value=v)
        if c == "Cancel here?": cell.fill = IN
ws["Z1"] = "40|6"
ws.column_dimensions["A"].width = 6
for col in range(2, 19): ws.column_dimensions[get_column_letter(col)].width = 15
# ---- Start here ----
ws = wb.create_sheet("Start here", 0)
lines = [("How to use this sheet", True), ("", False),
 ("1. Curve and Vols: paste the SONIA OIS rates and the swaption surface (normal vols by offset from ATM). Set the as-of date on Settings.", False),
 ("2. Structure: choose the swap term, the fixed rate we pay (or 'fair') and the coupon frequency. Type a preset (e.g. 'six dates') or tick dates yourself on Schedule.", False),
 ("3. Schedule: one row per coupon period. Tick 'Cancel here?' on the dates the bank may cancel. Turn the column into checkboxes once via Insert > Checkbox.", False),
 ("4. Set Settings!Run to TRUE. The Mac script (price_sheet.py --watch) prices it and writes Results and the per-date columns on Schedule. Status shows when it finished.", False),
 ("", False), ("Reading the results", True), ("", False),
 ("Cancel right, value to bank: what the bank's option is worth on the model. Coupon discount: what paying our fixed rate instead of the par rate is worth to us over the full term. The difference is the bank's take.", False),
 ("Intrinsic: the forward swap value on the best single date - pure curve arithmetic, nobody argues with it. Best European: that date's option on its own. Bermudan time value: what the other ticked dates add. Multiple = cancel right / best European; ~1.10 is model-fair, 1.07 is a good print, 1.00 means the bank pays only for one date.", False),
 ("Bank's take per +10 bp of rate: how much the bank's take rises when our fixed rate goes up 10 bp. Small (~£44k on the 40y) because the option is deep in the money - which is why bank charges and the multiple matter so much in rate terms.", False),
 ("", False), ("Things to try", True), ("", False),
 ("Untick every date but one (or preset 'single 2y'): the multiple goes to 1.00 and the value drops to the European. Tick six dates: most of the value comes back. Tick everything to year 40 ('full strip'): little changes past year 15.", False),
 ("Change the fixed rate: the cancel right and the coupon discount move together; watch the bank's take. Set the rate to 'fair' to solve where they cross.", False),
 ("Change Mean reversion (1% - 5%): only the Bermudan time value moves. Shift every vol by +10 bp: same. That is the model-dependent slice; everything else is the curve.", False),
 ("On Schedule, read 'Strike - forward' and 'Intrinsic if cancelled here': they show, before pricing, how deep in the money the bank is on each date.", False)]
for i, (t, bold) in enumerate(lines, 1):
    c = ws.cell(row=i, column=1, value=t); c.font = Font(bold=bold, size=12 if bold else 11)
ws.column_dimensions["A"].width = 140
import os
if os.environ.get("LITE"):
    ws = wb["Schedule"]
    ws.delete_rows(2, ws.max_row)
    ws["A3"] = "Empty until the first run: the Mac script builds one row per coupon period and applies Structure!Preset. Then tick 'Cancel here?' by hand (Insert > Checkbox on the column) or type a preset."
    ws["Z1"] = ""
    wb["Structure"]["B4"] = "semi-annual 2-15"
    wb.remove(wb["Collateral"])
    wb.save("LOBO_pricer_template_lite.xlsx"); print("lite ok")
else:
    wb.save("LOBO_pricer_template.xlsx"); print("xlsx ok")
