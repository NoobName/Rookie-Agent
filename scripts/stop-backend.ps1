$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$dataRoot=if ($env:AGENT_DATA) {$env:AGENT_DATA} else {Join-Path $projectRoot 'data'}
$clientToken=(Get-Content -LiteralPath (Join-Path $dataRoot 'client.token') -Raw).Trim()
$state=Invoke-RestMethod 'http://127.0.0.1:8765/api/bootstrap' -Headers @{Authorization='Bearer '+$clientToken}
if ($state.tasks | Where-Object {$_.state -in @('running','verifying','awaiting_approval')}) {throw '存在活动任务，请先在界面暂停或取消。'}
$owner=(Get-NetTCPConnection -LocalPort 8765 -State Listen).OwningProcess
$taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
if ($taskProcess.CommandLine -notmatch 'run_backend.py|local-agent-backend.exe') {throw '监听进程不是可识别的 Agent 后端，拒绝停止。'}
Stop-Process -Id $owner
Write-Host '共享后端已停止；网页和桌面客户端会断开。'
