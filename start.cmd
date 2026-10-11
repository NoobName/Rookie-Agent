@echo off
setlocal
cd /d "%~dp0"
if not defined AGENT_PYTHON set "AGENT_PYTHON=python"
"%AGENT_PYTHON%" scripts\launcher.py start %*
exit /b %errorlevel%
