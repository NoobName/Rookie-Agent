@echo off
setlocal
cd /d "%~dp0"
node node_modules\typescript\bin\tsc --noEmit
if errorlevel 1 exit /b %errorlevel%
node node_modules\vite\bin\vite.js build
exit /b %errorlevel%
