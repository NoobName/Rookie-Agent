// Copy runtime bytes, not source-tree ACLs. Do not disable Chromium's sandbox.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync, spawn } = require('node:child_process');

function runtime() {
  if (process.platform !== 'win32') return require('electron');
  const source = path.resolve(__dirname, '../node_modules/electron/dist');
  const executable = path.join(source, 'electron.exe');
  if (!fs.existsSync(executable)) throw Error('Electron runtime missing. Run setup.cmd first.');
  const version = fs.readFileSync(path.join(source, 'version'), 'utf8').trim();
  const hash = crypto.createHash('sha256').update(fs.readFileSync(executable)).digest('hex');
  const target = path.join(
    process.env.LOCALAPPDATA,
    'RookieAgent',
    'runtimes',
    `${version}-${hash.slice(0, 12)}`,
  );
  const cached = path.join(target, 'electron.exe');
  if (!fs.existsSync(path.join(target, '.ready'))) {
    fs.mkdirSync(target, { recursive: true });
    fs.cpSync(source, target, { recursive: true });
    const check = spawnSync(cached, ['--version'], {
      encoding: 'utf8',
      timeout: 15000,
      windowsHide: true,
    });
    if (check.status !== 0)
      throw Error(
        `Electron startup check failed (${check.status}). Install the desktop package in a normal per-user application directory.`,
      );
    fs.writeFileSync(path.join(target, '.ready'), hash);
  }
  return cached;
}

module.exports = { runtime };
if (require.main === module) {
  try {
    const executable = runtime();
    if (process.argv.includes('--check')) console.log(executable);
    else {
      const child = spawn(executable, [path.resolve(__dirname, '../apps/desktop/main.cjs')], {
        stdio: 'inherit',
        windowsHide: true,
      });
      child.on('error', (error) => {
        console.error(error.message);
        process.exitCode = 1;
      });
      child.on('exit', (code) => {
        process.exitCode = code ?? 1;
      });
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
