// Isolated UIA test target; no files, network, credentials, or user documents.
const { app, BrowserWindow } = require('electron');
app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 600,
    height: 350,
    title: 'Local Agent Desktop Test Fixture',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  await win.loadURL(
    'data:text/html;charset=utf-8,' +
      encodeURIComponent(
        '<title>Local Agent Desktop Test Fixture</title><h1>Agent UIA test target</h1><label>Smoke input <input aria-label="Smoke input" id="proof"></label><p>Only synthetic test text belongs here.</p>',
      ),
  );
  setTimeout(() => {
    win.show();
    win.focus();
  }, 500);
});
app.on('window-all-closed', () => app.quit());
