param([switch]$Check)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot/use-system-proxy.ps1"
$pythonExe=if($env:AGENT_PYTHON){$env:AGENT_PYTHON}else{'python'}
$pnpmExe=if($env:AGENT_PNPM){$env:AGENT_PNPM}else{'pnpm'}
if ($Check) {
    & $pythonExe --version
    if ($LASTEXITCODE -ne 0) {throw 'Python unavailable'}
    & $pnpmExe --version
    if ($LASTEXITCODE -ne 0) {throw 'pnpm unavailable'}
    node --version
    if ($LASTEXITCODE -ne 0) {throw 'Node unavailable'}
    exit 0
}
& $pythonExe -m pip install --target .runtime/python -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) {throw 'Python 依赖安装失败'}
& $pnpmExe install --frozen-lockfile
if ($LASTEXITCODE -ne 0) {throw '前端依赖安装失败'}
node node_modules/electron/install.js
if ($LASTEXITCODE -ne 0) {Write-Warning 'Electron 运行时下载失败；网页仍可使用，桌面启动前需要重试 node node_modules/electron/install.js。'}
& $pnpmExe build
if ($LASTEXITCODE -ne 0) {throw '网页构建失败'}
