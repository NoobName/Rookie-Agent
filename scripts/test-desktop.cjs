// Electron UI integration smoke, against an isolated backend data directory.
const { _electron: electron } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const root = path.resolve(__dirname, '..');
  const data = process.env.AGENT_DATA;
  if (!data || !path.resolve(data).startsWith(path.join(root, '.runtime') + path.sep))
    throw Error('Use isolated AGENT_DATA under .runtime');
  const watchdog = setTimeout(() => {
    console.error('Desktop smoke timed out');
    process.exit(1);
  }, 90000);
  const instance = await electron.launch({
    executablePath: process.env.AGENT_DESKTOP_EXE || require('./desktop-runtime.cjs').runtime(),
    args: [
      '--user-data-dir=' + path.join(data, 'desktop-profile'),
      ...(process.env.AGENT_DESKTOP_EXE ? [] : [path.join(root, 'apps/desktop/main.cjs')]),
    ],
    env: { ...process.env },
    timeout: 60000,
  });
  try {
    const window = await instance.firstWindow();
    await window.getByRole('button', { name: '＋ 新建会话' }).waitFor({ timeout: 60000 });
    assert.equal(await window.evaluate(() => typeof require), 'undefined');
    const config = await instance.evaluate(({ BrowserWindow }) => {
      const p = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
      return { node: p.nodeIntegration, isolation: p.contextIsolation, sandbox: p.sandbox };
    });
    assert.deepEqual(config, { node: false, isolation: true, sandbox: true });
    assert.equal(
      await instance.evaluate(({ app }) => app.commandLine.hasSwitch('no-sandbox')),
      false,
    );
    assert.equal(await instance.evaluate(() => process.argv.includes('--no-sandbox')), false);
    await window.getByRole('button', { name: '＋ 新建会话' }).click();
    await window.getByRole('button', { name: '深色模式', exact: true }).click();
    assert.equal(await window.locator('html').getAttribute('data-theme'), 'dark');
    await window.locator('.session-row.selected .session-more').click();
    await window.getByRole('menuitem', { name: '删除对话' }).waitFor();
    const point = await window.getByLabel('消息', { exact: true }).evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await window.mouse.move(point.x, point.y);
    assert.equal(
      await window.evaluate(
        (p) => document.elementFromPoint(p.x, p.y)?.getAttribute('aria-label'),
        point,
      ),
      '消息',
    );
    await window.keyboard.press('Escape');
    const token = fs.readFileSync(path.join(data, 'client.token'), 'utf8').trim();
    const base = 'http://127.0.0.1:' + (process.env.AGENT_PORT || 8765);
    const bootstrap = await (
      await fetch(base + '/api/bootstrap', { headers: { Authorization: 'Bearer ' + token } })
    ).json();
    assert(bootstrap.sessions.length > 0);
    await instance.evaluate(({ shell, Notification }) => {
      globalThis.approvalSignals = { beeps: 0, notifications: 0 };
      const beep = shell.beep;
      shell.beep = () => {
        globalThis.approvalSignals.beeps++;
        beep();
      };
      const show = Notification.prototype.show;
      Notification.prototype.show = function () {
        globalThis.approvalSignals.notifications++;
        return show.call(this);
      };
    });
    const post = async (route, body) =>
      (
        await fetch(base + route, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
      ).json();
    const task = await post('/api/sessions/' + bootstrap.sessions[0].id + '/tasks', {
      goal: 'Desktop approval notification test',
      workspace: '',
      deliverables: ['notification'],
      acceptance: ['review'],
      tools: ['terminal.run'],
      script: [
        { name: 'terminal.run', arguments: { argv: ['cmd', '/c', 'echo', 'NOTIFICATION_TEST'] } },
      ],
    });
    await post('/api/tasks/' + task.id + '/start', {});
    let signals;
    for (let i = 0; i < 50; i++) {
      signals = await instance.evaluate(() => globalThis.approvalSignals);
      if (signals.beeps && signals.notifications) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    assert(signals.beeps > 0, 'Approval must request native sound');
    assert(signals.notifications > 0, 'Approval must show native notification');
    await post('/api/tasks/' + task.id + '/cancel', {});
    await window.screenshot({ path: path.join(root, 'test-results/desktop.png') });
    await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
    assert.equal(
      await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()),
      false,
    );
    await instance.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].show());
    console.log('Desktop UI checks passed; requesting normal quit.');
    await instance.evaluate(({ app }) => {
      setTimeout(() => app.quit(), 0);
    });
    for (let i = 0; i < 100 && instance.process().exitCode === null; i++)
      await new Promise((r) => setTimeout(r, 100));
    assert.notEqual(instance.process().exitCode, null, 'Electron must exit after app.quit');
    assert.equal((await (await fetch(base + '/health')).json()).app, 'local-agent');
    console.log(
      'Electron passed: authenticated shared history, isolated renderer, close-to-tray, backend survives desktop exit.',
    );
  } finally {
    clearTimeout(watchdog);
    if (instance.process().exitCode === null) instance.process().kill();
  }
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
