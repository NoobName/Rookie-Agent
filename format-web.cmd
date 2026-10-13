@echo off
setlocal
cd /d "%~dp0"
set "FORMAT_MODE=--write"
if "%~1"=="--check" set "FORMAT_MODE=--check"
if not exist "node_modules\prettier\bin\prettier.cjs" (
  echo Prettier missing. Run setup.cmd first.
  exit /b 1
)
node node_modules\prettier\bin\prettier.cjs %FORMAT_MODE% apps packages tests/e2e scripts/*.cjs *.ts *.json .prettierrc.json
exit /b %errorlevel%
