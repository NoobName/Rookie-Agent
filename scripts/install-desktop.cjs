// Stage the built installer in the normal user application directory rather than
// running it with inherited source-workspace ACLs. No ACL or sandbox changes.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const version = require('../package.json').version;
const source = path.resolve(__dirname, `../release/Local Agent Workbench Setup ${version}.exe`);
try {
  if (process.platform !== 'win32') throw Error('The desktop installer requires Windows.');
  if (!fs.existsSync(source)) throw Error('Installer missing. Run package.cmd first.');
  const directory = path.join(process.env.LOCALAPPDATA, 'RookieAgent', 'installers', version);
  fs.mkdirSync(directory, { recursive: true });
  const target = path.join(directory, 'RookieAgentSetup.exe');
  fs.copyFileSync(source, target);
  const hash = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  if (hash(source) !== hash(target)) throw Error('Installer copy verification failed.');
  if (process.argv.includes('--check')) console.log(target);
  else {
    const child = spawn(target, ['/currentuser'], { stdio: 'inherit', windowsHide: true });
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
