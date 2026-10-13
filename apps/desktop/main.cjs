const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  Notification,
  Tray,
  Menu,
  shell,
} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../..');
const port = Number(process.env.AGENT_PORT || 8765),
  base = `http://127.0.0.1:${port}`;
let data =
  process.env.AGENT_DATA ||
  (app.isPackaged ? path.join(app.getPath('userData'), 'data') : path.join(root, 'data'));
let win,
  tray,
  quitting = false,
  owned = false,
  notificationTimer,
  token;
const preferenceFile = path.join(app.getPath('userData'), 'desktop-settings.json');
let preferences = { closeToTray: true, keepBackend: true };
try {
  const saved = JSON.parse(fs.readFileSync(preferenceFile, 'utf8'));
  for (const k of Object.keys(preferences))
    if (typeof saved[k] === 'boolean') preferences[k] = saved[k];
} catch {}
function save() {
  fs.mkdirSync(path.dirname(preferenceFile), { recursive: true });
  fs.writeFileSync(preferenceFile, JSON.stringify(preferences));
}
async function api(route, method = 'GET') {
  const r = await fetch(base + route, {
    method,
    headers: { Authorization: 'Bearer ' + token },
    signal: AbortSignal.timeout(4000),
  });
  if (!r.ok) throw Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}
async function healthy() {
  try {
    const nonce = crypto.randomBytes(16).toString('hex');
    const r = await fetch(base + '/discovery?nonce=' + nonce, {
      signal: AbortSignal.timeout(1500),
    });
    const info = await r.json();
    if (info.app !== 'local-agent' || !info.data_dir || !info.proof) return false;
    if (info.data_dir && info.proof) {
      if (
        process.env.AGENT_DATA &&
        path.resolve(data).toLowerCase() !== path.resolve(info.data_dir).toLowerCase()
      )
        return false;
      const candidate = fs.readFileSync(path.join(info.data_dir, 'discovery.key'), 'utf8').trim();
      const proof = crypto
        .createHmac('sha256', candidate)
        .update(nonce + '\n' + info.data_dir)
        .digest('hex');
      if (proof !== info.proof) return false;
      data = info.data_dir;
    }
    return true;
  } catch {
    return false;
  }
}
function trusted(event) {
  try {
    return (
      event.sender === win?.webContents &&
      event.senderFrame === win.webContents.mainFrame &&
      new URL(event.senderFrame.url).origin === base
    );
  } catch {
    return false;
  }
}
function show() {
  win?.show();
  win?.focus();
}
async function quit() {
  if (!preferences.keepBackend && owned) {
    try {
      await api('/api/shutdown', 'POST');
    } catch (e) {
      dialog.showErrorBox('后端仍在运行', String(e));
      return;
    }
  }
  quitting = true;
  clearInterval(notificationTimer);
  app.quit();
}
function menu() {
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '打开工作台', click: show },
      {
        label: '关闭窗口时最小化到托盘',
        type: 'checkbox',
        checked: preferences.closeToTray,
        click: (item) => {
          preferences.closeToTray = item.checked;
          save();
          menu();
        },
      },
      {
        label: '退出桌面后保留后台服务',
        type: 'checkbox',
        checked: preferences.keepBackend,
        click: (item) => {
          preferences.keepBackend = item.checked;
          save();
          menu();
        },
      },
      {
        label: '停止共享后台服务（所有客户端断开）',
        click: async () => {
          try {
            await api('/api/shutdown', 'POST');
            quitting = true;
            app.quit();
          } catch (e) {
            dialog.showErrorBox('无法停止', String(e));
          }
        },
      },
      { type: 'separator' },
      { label: '退出桌面', click: quit },
    ]),
  );
}
if (!app.requestSingleInstanceLock()) app.quit();
else
  app.whenReady().then(async () => {
    try {
      if (!(await healthy())) {
        const executable = app.isPackaged
          ? path.join(root, 'backend', 'local-agent-backend.exe')
          : process.env.AGENT_PYTHON || 'python';
        const args = app.isPackaged ? [] : [path.join(root, 'scripts', 'run_backend.py')];
        const child = spawn(executable, args, {
          cwd: root,
          env: {
            ...process.env,
            AGENT_DATA: data,
            AGENT_RESOURCE_ROOT: root,
            AGENT_PORT: String(port),
          },
          detached: true,
          stdio: 'ignore',
          windowsHide: true,
        });
        let spawnError;
        child.on('error', (e) => (spawnError = e));
        child.unref();
        owned = true;
        for (let i = 0; i < 60 && !(await healthy()); i++) {
          if (spawnError) throw spawnError;
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      if (!(await healthy())) throw Error('后端未启动，请运行 start.cmd 检查依赖和端口。');
      token = fs.readFileSync(path.join(data, 'client.token'), 'utf8').trim();
      await api('/api/bootstrap');
      win = new BrowserWindow({
        width: 1440,
        height: 950,
        minWidth: 850,
        minHeight: 650,
        title: 'Rookie Agent 工作台',
        backgroundColor: '#fafbf8',
        webPreferences: {
          preload: path.join(__dirname, 'preload.cjs'),
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: true,
        },
      });
      win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      win.webContents.on('will-navigate', (event, url) => {
        try {
          if (new URL(url).origin !== base) event.preventDefault();
        } catch {
          event.preventDefault();
        }
      });
      win.webContents.session.setPermissionRequestHandler((contents, permission, callback) =>
        callback(false),
      );
      win.on('focus', () => win.flashFrame(false));
      win.on('close', (event) => {
        if (!quitting) {
          event.preventDefault();
          if (preferences.closeToTray && tray) win.hide();
          else void quit();
        }
      });
      ipcMain.handle('directory', async (event) => {
        if (!trusted(event)) throw Error('Unauthorized IPC');
        const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
        return r.canceled ? null : r.filePaths[0];
      });
      ipcMain.handle('notify', async (event, title) => {
        if (!trusted(event) || typeof title !== 'string')
          throw Error(
            'Unauthorized IPC',
          ); /* Native notifications are delivered by the main-process poller. */
      });
      tray = new Tray(await app.getFileIcon(process.execPath));
      tray.setToolTip('Rookie Agent：后台任务与通知');
      tray.on('double-click', show);
      menu();
      const initial = await api('/api/notifications?latest=true');
      let cursor = initial.cursor;
      notificationTimer = setInterval(async () => {
        try {
          const r = await api('/api/notifications?after=' + cursor);
          for (const e of r.events) {
            cursor = Math.max(cursor, e.id);
            if (e.payload.kind === 'approval') {
              shell.beep();
              win?.flashFrame(true);
            }
            if (Notification.isSupported()) {
              const n = new Notification({
                title: 'Rookie Agent',
                body: String(e.payload.title || '任务状态更新').slice(0, 200),
                silent: e.payload.kind === 'approval',
              });
              n.on('click', show);
              n.show();
            }
          }
        } catch {}
      }, 2000);
      await win.loadURL(base + '/#token=' + encodeURIComponent(token));
    } catch (e) {
      dialog.showErrorBox('桌面启动失败', String(e));
      quitting = true;
      app.quit();
    }
  });
app.on('second-instance', show);
app.on('activate', show);
app.on('window-all-closed', () => {
  if (quitting) app.quit();
});
app.on('before-quit', () => {
  quitting = true;
  clearInterval(notificationTimer);
});
