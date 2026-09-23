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
rows = [("Term (years)", 40), ("Fixed rate %", 1.43), ("First call (years)", 2), ("Last call (years)", 15), ("Frequency (months)", 6), ("Explicit call years", ""), ("", ""),
        ("Notes", "Fixed rate: a number, or 'fair' to solve the model-fair rate and the dealt rates at the two take levels. Explicit call years (e.g. 2, 3, 5, 7, 10, 15) overrides first/last.")]
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
    ws.cell(row=i, column=4, value="=Results!$B$7"); ws.cell(row=i, column=5, value="=ROUND((B%d-D%d)*100,0)" % (i, i)); ws.cell(row=i, column=6, value="=E%d-Settings!$B$6*C%d" % (i, i))
    ws.cell(row=i, column=7, value='=IF(F%d>=Settings!$B$8,"target",IF(F%d>=Settings!$B$7,"minimum","out"))' % (i, i))
ws["I1"] = "Uses the fixed rate priced on the Structure tab (Results!B7). For a different term, re-price with that term."
ws = wb.create_sheet("Collateral"); head(ws, 1, ["Rates move (parallel)", "Investor posts £", "% of notional"])
for i, (m, v, p) in enumerate([("+50 / +100 bp", 0, 0), ("-25 bp", 160000, 1.6), ("-50 bp", 340000, 3.4), ("-100 bp", 750000, 7.5), ("-150 bp", 1260000, 12.6), ("-200 bp", 1890000, 18.9), ("-300 bp", 3650000, 36.5)], 2):
    ws.cell(row=i, column=1, value=m); ws.cell(row=i, column=2, value=v); ws.cell(row=i, column=3, value=p)
head(ws, 11, ["Year", "Swap still alive", "Average posting £", "95th percentile £", "99th percentile £"])
for i, r in enumerate([(2, "100%", 800000, 3900000, 7800000), (3, "41%", 800000, 4300000, 9300000), (5, "27%", 700000, 4200000, 10100000), (7, "19%", 600000, 3700000, 10600000), (10, "13%", 400000, 2300000, 9200000), (15, "5%", 200000, 0, 5000000)], 12):
    for j, v in enumerate(r, 1): ws.cell(row=i, column=j, value=v)
ws["G1"] = "Reference: 40y at 1.43%, semi-annual 2-15, £10m, live data 2026-09-22 (from the briefing). Not recomputed by the slim script."
for w in wb.worksheets:
    for col in range(1, 25): w.column_dimensions[get_column_letter(col)].width = 14 if col > 1 else 30
wb.save("LOBO_pricer_template.xlsx"); print("xlsx ok")
