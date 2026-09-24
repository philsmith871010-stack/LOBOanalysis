// Gives the sheet a "LOBO > Price now" menu and makes the Run tick box call the pricer.
// Setup: Extensions > Apps Script, paste this over the default code, save, reload the sheet.
// Cloud Run: Project Settings (gear) > Script properties: PRICER_URL = the service URL, PRICER_TOKEN = its PRICER_TOKEN env var.
// Then run installTriggers once from the editor (Run > installTriggers) so ticking Run also calls Cloud Run.
// Without PRICER_URL the menu just ticks Run for the Mac watcher.
// Optional button: Insert > Drawing, draw a shape labelled "Price", insert, its three dots > Assign script > priceNow.

var RESULT_RANGES = ['B16:B31', 'B34:B36', 'B39:B51', 'D17:F120'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('LOBO').addItem('Price now', 'priceNow').addToUi();
}

function clearResults_(sh) {
  RESULT_RANGES.forEach(function (r) { sh.getRange(r).clearContent(); });
  var sc = SpreadsheetApp.getActive().getSheetByName('Schedule');
  if (sc && sc.getLastRow() > 1) sc.getRange(2, 17, sc.getLastRow() - 1, 3).clearContent();   // European value, vol, probability
}

function priceNow() {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName('Pricer');
  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('PRICER_URL'), token = props.getProperty('PRICER_TOKEN');
  var now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'HH:mm:ss');
  clearResults_(sh);
  if (!url) {                                                    // Mac watcher mode
    var hb = String(sh.getRange('B13').getValue());
    sh.getRange('B11').setValue(true);
    sh.getRange('B12').setValue(now + '  queued for the Mac' + (hb.indexOf('Mac connected') === 0 ? '' : '  (watcher not connected: run price_sheet.py --watch)'));
    return;
  }
  sh.getRange('B12').setValue(now + '  calling Cloud Run...');
  var res = UrlFetchApp.fetch(url.replace(/\/$/, '') + '/price', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    payload: JSON.stringify({ sheet: ss.getId(), token: token })
  });
  var code = res.getResponseCode(), text = res.getContentText();
  if (code !== 202) sh.getRange('B12').setValue(now + '  Cloud Run refused (' + code + '): ' + text);
}

// Installable edit trigger: ticking Run (B11) calls priceNow. Run installTriggers() once from the editor.
function onRunTick(e) {
  if (!e || !e.range) return;
  var sh = e.range.getSheet();
  if (sh.getName() === 'Pricer' && e.range.getA1Notation() === 'B11' && e.range.getValue() === true) priceNow();
}

function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'onRunTick') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('onRunTick').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
}
