# LOBO cancellable-swap pricer

Prices a swap that the bank can cancel on a set of dates (a payer Bermudan on the remaining swap) from two inputs:
the SONIA OIS curve and the GBP swaption surface. One-factor Gaussian short-rate model (QuantLib `Gsr`), calibrated
at the strike to the co-terminal swaptions, smile from a shifted-SABR fit per surface row. Produces the value of the
cancel right, what the coupon discount is worth, the bank's implied take, the European ladder, the best European and
the multiple. Optionally solves the fair rate and the rate at a given bank take.

## Mac setup (once)

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -q                     # pins the numbers from the briefing paper (takes ~2 min)

## Google Sheet

Use the shared template (tabs `Curve`, `Vols`, `Settings`, `Structure`, `Results`, `Portfolio`, `Collateral`).
Paste the curve into `Curve` (tenor, rate %) and the surface into `Vols` (expiry y, tenor y, ATM strike %, then the
normal vols under the bp-offset headers — any column order, the header decides). Fill `Settings` and `Structure`.

To let the script read and write the sheet you need a Google *service account*:

1. console.cloud.google.com → create a project (no billing) → APIs & Services → enable **Google Sheets API** and **Google Drive API**.
2. IAM & Admin → Service Accounts → Create → Keys → Add key (JSON). Save it as `sa-key.json` next to this README. Never share it.
3. Share the Google Sheet with the service account's email address (Editor), like you would with a colleague.

## Run

    python price_sheet.py --sheet "<sheet url>" --once            # price now and exit (~5-10 s with a fixed rate, ~1 min with "fair")
    python price_sheet.py --sheet "<sheet url>" --watch           # leave running; a colleague sets Settings!Run to TRUE to price

`Structure!Fixed rate %` takes a number (e.g. `1.43`) or the word `fair`, in which case the script also solves the
dealt rates at the two bank-take levels in `Settings`. Results land in `Results` with a timestamp; the European ladder
sits in columns E-G. `caffeinate -i python price_sheet.py ... --watch` keeps the Mac awake while it runs.

## Layout of the package

    pricer/market.py     curve, SABR surface, swap builder
    pricer/structure.py  CallableSwap + price()  (cancel right, coupon discount, take, European ladder, multiple)
    pricer/solve.py      rate_for_take() / fair_rate()  (secant on the bank's take)
    pricer/data.py       the live data set used by the tests, and the sheet-row parser
    price_sheet.py       Google Sheet glue
