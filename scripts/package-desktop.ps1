$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
pnpm build
if ($LASTEXITCODE -ne 0) {throw '网页构建失败'}
python scripts/package-backend.py
if ($LASTEXITCODE -ne 0) {throw '后端打包失败'}
New-Item -ItemType Directory -Force dist/backend | Out-Null
Copy-Item -Path dist/backend-build/local-agent-backend/* -Destination dist/backend -Recurse -Force
# Explicit packaging-only dependency. Development dependencies do not require native node-gyp.
pnpm dlx electron-builder@26.0.12 --config apps/desktop/builder.json
if ($LASTEXITCODE -ne 0) {throw 'Electron 安装包构建失败；检查官方下载与 node-gyp 依赖访问'}
