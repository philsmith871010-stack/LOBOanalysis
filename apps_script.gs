// Gives the sheet a "LOBO > Price now" menu and makes the Run tick box call the pricer.
// Setup: Extensions > Apps Script, paste this over the default code, save, reload the sheet.
// Cloud Run: Project Settings (gear) > Script properties: PRICER_URL = the service URL, PRICER_TOKEN = its PRICER_TOKEN env var.
// Then run installTriggers once from the editor (Run > installTriggers) so ticking Run also calls Cloud Run.
// Without PRICER_URL the menu just ticks Run for the Mac watcher.
// Cells are found by their labels in column A, so layout changes do not need this script re-pasted.

function onOpen() {
  SpreadsheetApp.getUi().createMenu('LOBO').addItem('Price now', 'priceNow').addToUi();
}

function rowOf_(sh, label) {                  // row number whose column-A label starts with `label`
  var col = sh.getRange('A1:A100').getValues();
  for (var i = 0; i < col.length; i++) if (String(col[i][0]).indexOf(label) === 0) return i + 1;
  return 0;
}

function clearResults_(sh) {
  var spec = String(sh.getRange('Z3').getValue() || '');          // the pricer lists the result ranges here
  spec.split(',').forEach(function (r) { r = r.trim(); if (r) sh.getRange(r).clearContent(); });
  var sc = SpreadsheetApp.getActive().getSheetByName('Schedule');
  if (sc && sc.getLastRow() > 1) sc.getRange(2, 17, sc.getLastRow() - 1, 3).clearContent();   // European value, vol, probability
}

function priceNow() {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName('Pricer');
  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('PRICER_URL'), token = props.getProperty('PRICER_TOKEN');
  var now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'HH:mm:ss');
  var runRow = rowOf_(sh, 'Run'), statusRow = rowOf_(sh, 'Status'), engineRow = rowOf_(sh, 'Engine');
  clearResults_(sh);
  if (!url) {                                                    // Mac watcher mode
    var hb = engineRow ? String(sh.getRange(engineRow, 2).getValue()) : '';
    if (runRow) sh.getRange(runRow, 2).setValue(true);
    if (statusRow) sh.getRange(statusRow, 2).setValue(now + '  queued for the Mac' + (hb.indexOf('Mac connected') === 0 ? '' : '  (watcher not connected: run price_sheet.py --watch)'));
    return;
  }
  if (statusRow) sh.getRange(statusRow, 2).setValue(now + '  calling Cloud Run...');
  var res = UrlFetchApp.fetch(url.replace(/\/$/, '') + '/price', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    payload: JSON.stringify({ sheet: ss.getId(), token: token })
  });
  var code = res.getResponseCode(), text = res.getContentText();
  if (code !== 202 && statusRow) sh.getRange(statusRow, 2).setValue(now + '  Cloud Run refused (' + code + '): ' + text);
}

// Installable edit trigger: ticking Run calls priceNow. Run installTriggers() once from the editor.
function onRunTick(e) {
  if (!e || !e.range) return;
  var sh = e.range.getSheet();
  if (sh.getName() !== 'Pricer' || e.range.getColumn() !== 2 || e.range.getValue() !== true) return;
  if (e.range.getRow() === rowOf_(sh, 'Run')) priceNow();
}

function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'onRunTick') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('onRunTick').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
}
