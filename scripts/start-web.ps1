param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path 'dist/web/index.html')) { throw '请先运行 pnpm build 构建网页。' }
$healthy=$false
try { $healthy=(Invoke-RestMethod 'http://127.0.0.1:8765/health').app -eq 'local-agent' } catch {}
if (-not $healthy) {
  $pythonExe=if ($env:AGENT_PYTHON) {$env:AGENT_PYTHON} else {(Get-Command python).Source}
  Start-Process -FilePath $pythonExe -ArgumentList @('scripts/run_backend.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput 'data-backend.log' -RedirectStandardError 'data-backend-error.log'
  for ($i=0; $i -lt 60; $i++) { Start-Sleep -Milliseconds 500; try { $healthy=(Invoke-RestMethod 'http://127.0.0.1:8765/health').app -eq 'local-agent'; if ($healthy) {break} } catch {} }
}
if (-not $healthy) {throw '后端启动失败，请查看 data-backend-error.log'}
$dataRoot=if ($env:AGENT_DATA) {$env:AGENT_DATA} else {Join-Path $projectRoot 'data'}
$clientToken=(Get-Content -LiteralPath (Join-Path $dataRoot 'client.token') -Raw).Trim()
if (-not $NoBrowser) { Start-Process ('http://127.0.0.1:8765/#token='+$clientToken) }
Write-Host '本地服务已启动：http://127.0.0.1:8765。关闭网页不会停止后端。'
