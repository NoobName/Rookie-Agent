@echo off
setlocal
cd /d "%~dp0"
if defined AGENT_PYTHON (
  "%AGENT_PYTHON%" scripts\format.py %*
) else (
  python scripts\format.py %*
)
if errorlevel 1 exit /b %errorlevel%
call format-web.cmd %*
exit /b %errorlevel%
