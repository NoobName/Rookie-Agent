# 本地 Agent 工作台

Windows 本地优先的个人 Agent 原型。React + TypeScript 网页、Electron 桌面入口、Python FastAPI、SQLite。无需 API 密钥即可演示真实 coding 工具闭环。

**这是可运行的开发版本，不是原始七阶段需求的全部完成版本。** 完成范围与缺口见 [验收矩阵](docs/acceptance.md)。Scripted Provider 是固定演示，不具备通用智能。

## 启动

已有项目依赖的本机，推荐直接在 **CMD** 中执行：

```cmd
cd /d D:\UCL\render\agent
build.cmd
start.cmd
```

`start.cmd` 打开浏览器并自动认证；`status.cmd` 查看状态；`stop.cmd` 优雅停止后端。有执行中或排队任务时，先在页面暂停或取消。关闭浏览器会保留后台服务。启动失败时查看 `data\backend-error.log`。若 Python 不在 PATH，可先执行 `set "AGENT_PYTHON=你的Python完整路径"`。

测试入口：

```cmd
test.cmd -q --basetemp .runtime\manual-tests
```

首次安装依赖需要 Python 3.13、Node.js 22+ 和 pnpm，可从 CMD 调用现有安装脚本：

```cmd
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
build.cmd
start.cmd
```

原 PowerShell 入口仍保留：

```powershell
cd D:\UCL\render\agent
./scripts/setup.ps1
./scripts/start-web.ps1
```

已有依赖与网页构建时直接运行 `scripts/start-web.ps1`。若 PowerShell 禁止运行脚本，可使用 `powershell -ExecutionPolicy Bypass -File scripts/start-web.ps1`，仅对此进程生效。

网页地址为 http://127.0.0.1:8765；启动器自动传递本机令牌，不要分享含令牌的链接。首次进入选择“验证 coding 闭环”，保存计划、开始执行、批准文件写入和 Python 测试，然后下载产物、接受结果。

桌面：`pnpm desktop` 或 `scripts/start-desktop.ps1`。Electron 官方运行时需安装成功（`node node_modules/electron/install.js`）。本次环境官方 GitHub 下载失败，桌面窗口尚未实测。网页与桌面访问同一个后端及数据库。关闭窗口**默认保留后台服务**，不会中断其他客户端；当前尚无托盘退出控制。新版用 `stop.cmd` 停止无活动任务的共享后端。升级前已运行的旧后端需要先通过旧版 `scripts/stop-backend.ps1` 停止，再运行 `start.cmd`。

不依赖 pnpm 的已安装环境可用：`node node_modules/typescript/bin/tsc --noEmit`、`node node_modules/vite/bin/vite.js build`、`python scripts/run_backend.py`。

## 配置 API

在“模型与设置”填写唯一配置 ID、显示名称、真实模型 ID、Base URL（如服务文档规定的 `/v1` 前缀）。后端追加 `/chat/completions`，不猜测模型能力。

密钥仅通过独立接口保存到 Windows Credential Manager，SQLite 只保存随机引用；不支持安全后端时会拒绝明文回退。保存后执行连接测试。工具执行需要模型确实支持原生 tool calls 并勾选工具能力。支持独立普通聊天、流式、工具协议与视觉样本测试；一次样本通过不等于通用能力排名。图片在用户明确附加后按模型视觉配置发送。

0.2.1：保存后密钥框清空是避免回显，旁边显示实际凭据保存状态。留空再次保存会保留密钥，输入新密钥才替换。配置 ID、显示名称和服务商模型 ID 不同；模型 ID 不能为空。已有配置可点击“获取已保存配置的模型列表”，选择服务商返回的模型 ID 后保存。修改未保存时禁用测试，避免误测旧配置。失败会显示 HTTP 状态及对应排查建议，不回显服务商可能包含密钥的原始错误正文。

设置页可删除选中的模型及其凭据；内置演示模型不能删除。活动请求/任务或启用的定时任务正在使用模型时会阻止删除。侧栏可删除当前会话、消息、任务记录和关联定时任务；活动请求或任务必须先结束或暂停。工作区产物、附件文件、独立记忆、累计用量和既有备份保留，不删除用户文件。

多模型默认关闭。在任务计划开启“多模型只读咨询”，填写 `角色=provider ID`。主模型最多分派三个串行咨询任务；子模型无工具、无递归权限，结果不能直接当作验证通过。失败回退单模型。当前协作不支持硬预算组合，接口会明确拒绝。真实多模型质量及成本等待用户 API 实测。

## 权限与数据

- 问答不会执行工具。执行模式展示计划、目标、交付物和验收条件。
- 逐次询问：每个工具动作审批。工作区自动模式：允许范围内读取、列目录、新建文件；覆盖仍确认并检查读取时的 SHA-256。
- 终端、MCP、浏览器和桌面默认逐次确认。可显式批准“本任务”或“此工作区”中工具和参数完全相同的操作，指定有效期（默认 1 小时，最多 168 小时）。更换命令/参数需要新授权，任务工具清单仍然生效；设置页可查看规则及撤销。终端不是沙箱，可访问用户系统资源。按目录的通配授权尚未实现。
- 暂停/取消停止后续调度，终端取消清理该调用启动的进程树。不可取消的同步文件/文档操作可能完成，恢复前必须审查实际文件。
- 重启将活动任务标为中断暂停。等待授权但尚未执行的调用标为“未执行”，继续时重新检查授权。执行中断且副作用不确定的调用必须填写审查说明，选择“跳过”或“重新尝试”；跳过不会改写历史为成功。新版 Scripted 保存工作流步骤，继续时不重写已完成文件。旧版缺少步骤记录的 Scripted 任务仍需新建后续任务，不能猜测重放位置。
- `data/` 保存数据库、认证令牌、附件、演示工作区和技能，不加入版本库。可用 `AGENT_DATA` 指定单独目录，所有客户端必须一致。
- 个人记忆提供给问答，个人及工作区记忆提供给任务；按全文/中文子串查询并回退到近期范围记录，未实现语义向量检索。用户可编辑/删除，索引同步删除。
- 附件上传真实保存；常见文本、DOCX/XLSX/PDF 会解析后送入所选任务/问答；图片和粘贴截图需要模型启用视觉能力。网页不能任意浏览本地目录；可手动填写工作区，桌面提供原生目录选择。

## 工具与扩展

0.3.0 新增：聊天支持安全的代码块、复制代码、行内代码、粗体、基础标题/列表及 HTTP(S) 链接；原始 HTML 不执行，不自动加载外部图片。暂不提供完整 CommonMark、表格、数学公式或语法高亮。

记忆页可选择“明确事实 / 模型推断 / 待确认”，查看来源与时间、编辑前版本、全文/中文子串检索并导出 JSON。编辑同步更新检索索引；删除同时移除该记忆、版本历史和索引。历史执行审计、已发送给模型的内容和既有备份保留，不会假装撤回外部模型已收到的内容。

“接受任务结果后自动保存项目验收摘要”默认关闭。启用后仅在用户接受结果时，将目标、交付物和实际检查结果保存到对应工作区范围，不额外调用模型或推断事实。关闭后不再自动保存；已有摘要可像普通记忆一样删除。摘要记录可在后续相同工作区任务中检索，个人范围记忆用于新会话。

在“扩展与自动化 → 技能”选择“项目检查”或“资料整理”，点击“使用此技能创建计划”。填写工作区、技能所需输入与实际交付物，再审查并保存计划。技能内容以快照写入上下文，后续修改技能文件不改变已保存任务；不会自动执行或绕过工具授权。技能保存校验字段和工具依赖，重复保存自动递增版本并保留历史文件。

任务计划中可添加“实际验收检查”：文件存在、文本包含、命令退出码为 0 或人工确认。机器检查由执行器触发，模型不能修改检查条件；命令检查需要同样的执行授权。验收失败会将真实证据交回模型，最多按配置尝试修复。Scripted 不能自主修复任意任务，会保留失败证据并停止；同一操作修复后真正成功，不再被旧失败永久阻止验收。文字验收项始终由用户最终确认。

执行中可以在消息框提交反馈：先暂停旧执行、保存补充，再审查计划并继续。可能已发生的副作用仍需要恢复审查。计划修改会使旧验收报告失效。执行保护设置包含最多模型轮次、修复轮次和暂时网络失败重试；重试只针对未派发工具的模型请求，不自动重试外部副作用。失败的供应商请求可能仍计费，本地无法确认其 token 用量。

文件读写、Git status/diff、逐次授权的 Git commit、真实 argv 终端，以及仅针对自身记录且不覆盖后续用户编辑的回退；txt/md/json/csv/docx/xlsx/pdf 常见读取/创建并重新解析。文档不覆盖原件；复杂格式修改、公式重算、OCR 和布局渲染尚未完成。

浏览器：`node node_modules/@playwright/test/cli.js install chromium`。独立持久 profile 位于任务工作区 `.agent-browser-profile`，观察后才能操作；表单提交有独立动作。当前是无头浏览器，交互登录接管和通用视觉观察仍待完善。

MCP：`mcp.call` 支持 stdio 和 Streamable HTTP；发现也须授权启动/连接。示例 `examples/mcp_server.py` 提供 add 和失败工具。扩展页可保存配置并创建授权连接测试任务；远程 OAuth 和复杂认证仍未支持。

技能：扩展页查看/编辑 JSON 示例，保存历史版本并选用生成任务计划；技能不会自动成为系统授权。任务计划还可使用结构化预置工作流，每个动作仍按统一策略授权。

定时：扩展页从所选任务生成配置，支持单次/间隔、IANA 时区、授权截止、漏执行跳过/补一次、暂停取消。只在本地服务运行时执行，按单任务队列入队；工具授权重新校验。搜索可配置真实 HTTPS API（包含 Brave 格式示例）。SMTP 邮箱默认禁用，显式配置后 email.send 可通过 SSL 发送；连接邮箱不等于自动授权发信，每次具体内容仍需确认。发送链路仅测试了记录传输器，真实邮箱尚未实测。

Windows UIA：安装 `requirements-optional.txt`；扩展页手动启用，任务选择 desktop.action 并逐次批准。紧急停止 **Ctrl+Alt+F12** 或页面按钮。优先控件，不连续盲点；焦点改变、窗口移动、观察过期拒绝输入。实机前台交互尚待手工验收，见 `scripts/windows-smoke.ps1`。

## 测试与打包

```powershell
python scripts/test.py -q --basetemp .runtime/test-manual
pnpm build
# 先启动本地后端，再运行：
pnpm test:e2e
```

E2E 会创建演示会话和工作区，建议在 CMD 使用独立数据与端口：

```cmd
set "AGENT_DATA=D:\UCL\render\agent\.runtime\my-e2e"
set "AGENT_PORT=8776"
start.cmd --no-browser
node node_modules\@playwright\test\cli.js test --max-failures=1
stop.cmd
```

若测试失败并留下活动任务，先通过该端口的页面暂停或取消，再停止。证据截图位于 `test-results/workbench.png` 和 `test-results/verification.png`。后端 39 项、网页 9 条 E2E 已通过；详见 `docs/verification.json`。

安装包流程在 `scripts/package-desktop.ps1`：网页构建 → PyInstaller 后端 → electron-builder NSIS。需要可访问官方 Electron/构建依赖。后端 EXE 已实际构建并在独立资源目录通过 HTTP、认证 API 和 DOCX 创建/重新解析 smoke test；位置 `dist/backend-build/local-agent-backend/`（整个目录一并使用）。**完整 Electron/NSIS 安装包仍未构建成功。** 打包版演示 coding 仍需要本机 Python 解释器。
