// Optional: gives the sheet a "LOBO > Price now" menu and a function you can attach to a drawn button.
// Extensions > Apps Script, paste this over the default code, save, reload the sheet.
// For a button: Insert > Drawing, draw a shape labelled "Price", insert it, click its three dots > Assign script > priceNow.
function onOpen() {
  SpreadsheetApp.getUi().createMenu('LOBO').addItem('Price now', 'priceNow').addToUi();
}
function priceNow() {
  var sh = SpreadsheetApp.getActive().getSheetByName('Pricer');
  var hb = String(sh.getRange('B13').getValue());
  var now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'HH:mm:ss');
  ['B16:B31', 'B34:B36', 'B39:B51', 'D17:F120'].forEach(function (r) { sh.getRange(r).clearContent(); });
  var sc = SpreadsheetApp.getActive().getSheetByName('Schedule');
  if (sc && sc.getLastRow() > 1) sc.getRange(2, 17, sc.getLastRow() - 1, 3).clearContent();   // European value, vol, probability columns
  sh.getRange('B11').setValue(true);
  var warn = hb.indexOf('connected ') === 0 ? '' : '  (Mac watcher not connected: run price_sheet.py --watch)';
  sh.getRange('B12').setValue(now + '  queued' + warn);
}
