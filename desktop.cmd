@echo off
cd /d "%~dp0"
if not exist "node_modules\electron\dist\electron.exe" (
  echo Electron runtime missing. Run node node_modules/electron/install.js first.
  exit /b 1
)
node scripts\desktop-runtime.cjs
exit /b %errorlevel%
