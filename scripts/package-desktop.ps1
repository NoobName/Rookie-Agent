$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot/use-system-proxy.ps1"
cmd /c build.cmd
if ($LASTEXITCODE -ne 0) {throw '网页构建失败'}
$pythonExe=if($env:AGENT_PYTHON){$env:AGENT_PYTHON}else{'python'}
& $pythonExe scripts/package-backend.py
if ($LASTEXITCODE -ne 0) {throw '后端打包失败'}
New-Item -ItemType Directory -Force dist/backend | Out-Null
Copy-Item -Path dist/backend-build/local-agent-backend/* -Destination dist/backend -Recurse -Force
# Explicit packaging-only dependency. Development dependencies do not require native node-gyp.
$pnpmExe=if($env:AGENT_PNPM){$env:AGENT_PNPM}else{'pnpm'}
& $pnpmExe dlx electron-builder@26.15.3 --config apps/desktop/builder.json --config.electronDist=node_modules/electron/dist
if ($LASTEXITCODE -ne 0) {throw 'Electron 安装包构建失败；检查官方下载与 node-gyp 依赖访问'}
