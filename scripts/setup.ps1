$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
python -m pip install --target .runtime/python -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) {throw 'Python 依赖安装失败'}
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) {throw '前端依赖安装失败'}
node node_modules/electron/install.js
if ($LASTEXITCODE -ne 0) {Write-Warning 'Electron 运行时下载失败；网页仍可使用，桌面启动前需要重试 node node_modules/electron/install.js。'}
pnpm build
if ($LASTEXITCODE -ne 0) {throw '网页构建失败'}
