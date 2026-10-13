@echo off
setlocal
cd /d "%~dp0"
node scripts\install-desktop.cjs %*
exit /b %errorlevel%
