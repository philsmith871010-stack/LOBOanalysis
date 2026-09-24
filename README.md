# LOBO cancellable swap pricer

QuantLib-Python pricer for a cancellable swap (we pay a low fixed rate vs SONIA; the bank may cancel on ticked coupon dates),
driven from a Google Sheet. The Python runs on your Mac and talks to the sheet through a Google service account. Nothing is hosted.

Model: SONIA OIS curve, shifted-SABR smile per surface row, one-factor Gaussian (Hull-White / LGM) calibrated to the
co-terminal swaptions at the strike, Bermudan priced by backward induction. Cash-settled (collateralised cash price).

## The sheet (3 tabs)

- **Pricer**: blue cells are inputs (term, fixed rate or `fair`, frequency, notional, call-date preset, run mode, Run tick).
  Results fill below: cancel right, coupon discount, bank's take, best European, multiple, time value. A European ladder to the right,
  and a Portfolio block showing the net spread on each LOBO at the priced rate. Assumptions (reversion, take levels, spread targets) at the bottom.
- **Market**: as-of date, SONIA OIS par rates, and the swaption normal-vol surface by offset from ATM. Paste over the blocks.
- **Schedule**: one row per coupon period (dates, cashflows, DF, PV, forward rate, intrinsic if cancelled here). The ticks in
  "Cancel here?" are the call schedule. After a run the European value, normal vol and (Full run) cancel probability are filled per ticked date.

Run mode **Quick** (about 10 s): price, ladder, multiple. **Full** (about 1 min): adds sensitivities to rate / vol / reversion, exercise
probabilities, expected life and collateral postings under parallel shifts. Typing `fair` as the fixed rate solves the model-fair rate and
the two dealt rates first (about 2 min); the cell then shows the solved rate.

## Mac setup (once)

```
git clone https://github.com/philsmith871010-stack/LOBOanalysis.git
cd LOBOanalysis
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
pytest -q                      # 4 tests, about 2 minutes
```

Service account: Google Cloud console > new project > enable **Google Sheets API** and **Google Drive API** > Credentials > Service account >
Keys > add JSON key. Save the file as `sa-key.json` in this folder (git-ignored). Share the sheet with the service account's
`client_email` as Editor.

## Running

```
python price_sheet.py --sheet <sheet id or url> --key sa-key.json --init     # build or repair the 3-tab layout (once per sheet)
python price_sheet.py --sheet <sheet id or url> --key sa-key.json --watch    # leave running; prices whenever Pricer!Run is ticked
python price_sheet.py --sheet <sheet id or url> --key sa-key.json --once     # price now and exit
```

`--init` works on a blank sheet, and on a sheet with the older Curve / Vols / Settings / Structure tabs (it carries the data over and
removes the old tabs). While `--watch` runs, the Pricer tab shows "connected hh:mm:ss" next to Mac watcher; the Run tick is picked up
within 3 seconds and Status shows progress.

Optional button: paste `apps_script.gs` into Extensions > Apps Script. That adds a **LOBO > Price now** menu (and a function to attach to a
drawn button) which ticks Run and warns if the Mac watcher is not connected.

## Layout

- `pricer/market.py`: curve, pseudo-Ibor SONIA index, SABR fits, `nvol()`, `shifted()` for bumped markets.
- `pricer/structure.py`: `CallableSwap`, `price()`: calibrate, price the Bermudan, European ladder, multiple.
- `pricer/solve.py`: `rate_for_take()`, `fair_rate()`.
- `pricer/analysis.py`: `sensitivities()`, `exercise_profile()` (expected life, cancel probabilities), `collateral()`.
- `pricer/schedule.py`: per-period schedule rows and the named presets.
- `sheet_layout.py`: the sheet layout (cell positions, formats, dropdowns, checkboxes) and `init_sheet()`.
- `price_sheet.py`: reads the sheet, runs, writes back; `--init`, `--once`, `--watch`.
- `apps_script.gs`: optional menu / button.
