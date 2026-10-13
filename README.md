# Rookie Agent 工作台

当前版本：**0.7.2**。Windows 本地优先的个人 Agent，React 网页与 Electron 桌面共用 FastAPI、SQLite、单任务队列和执行记录。

## Agent 执行能力

- `workspace.inspect`：检查多层项目目录、构建配置、package scripts 和可用工具路径，优先沿用已有工程。发现配置不代表已执行构建。
- `files.edit`：按旧文本/新文本局部修改源码，保留其余内容、UTF-8 BOM 和 CRLF；使用读取时的 SHA-256 防止覆盖过期版本，提供差异、产物和修改记录。新文件仍用 `files.write`。
- `task.plan`：模型维护步骤、当前进展和下一步；保存到 SQLite，后续请求及暂停恢复自动带入最新工作记录。对话中默认折叠展示步骤。它不修改用户验收要求，也不把步骤完成当作测试通过。

新建任务和可执行问答均可使用这些工具；旧任务保留原工具范围，可在“编辑计划 / 继续”中添加。工作区内检查与源码修改遵循“帮我审批”，终端沿用已有授权。已用固定模型调用序列跑通真实的光照函数局部修复与 Python 测试；真实模型的任务选择和长期完成质量仍需另行评估。

## 用 CMD 启动

首次准备需要 Python 3.11+、Node.js 和 pnpm（`setup.cmd -Check` 可先检查三者是否可用）：

```cmd
cd /d D:\UCL\render\agent
setup.cmd
start.cmd
```

已安装依赖后：`build.cmd` 构建网页，`start.cmd --no-browser` 启动服务，`status.cmd` 查看状态，`stop.cmd` 优雅关闭。默认端口 8765。执行中或队列非空时停止服务会被拒绝，请先暂停或取消任务。

`desktop.cmd` 启动源码桌面端；`package.cmd` 构建安装包；`install-desktop.cmd` 从普通用户应用目录运行安装器。当前包为 `release/Local Agent Workbench Setup 0.7.2.exe`。本机实际安装、桌面启动、通知、托盘、沙箱和打包后端 DOCX 检查已通过。

本机受限工作区内的 Electron 会在初始化沙箱时退出（0x80000003）；同一二进制复制到普通用户目录即可启动。源码启动器将运行时缓存到 `%LOCALAPPDATA%\RookieAgent\runtimes`；安装入口将安装器复制并校验到用户目录。没有关闭沙箱、调整工作区 ACL 或全局系统防护。不要把 `release/win-unpacked` 在受限工作区里双击失败当作最终安装版验收；使用 `install-desktop.cmd` 安装。桌面关闭窗口可驻留托盘，网页和桌面共享服务数据。

可在 CMD 设置 `AGENT_PYTHON`、`AGENT_PNPM` 指定解释器与 pnpm 路径；`AGENT_DATA`、`AGENT_PORT` 用于隔离测试数据与端口。不要让两个服务同时写同一数据目录。

## 使用

1. 在“模型与设置”填写兼容 Chat Completions 的 Base URL、模型 ID 和密钥，按实际支持启用工具、流式、视觉能力。密钥保存在操作系统凭据存储中；保存后输入框留空表示不回显，留空再次保存会保留原密钥。
2. 新建项目并选择工作区，或使用默认工作区。普通“发送”支持问答、工具执行与文件交付；“创建任务”支持先编辑计划、验收条件与执行保护。
3. 底部选择模型、权限模式和单模型/多模型协作。“帮我审批”自动批准工作区内的读写及文档修改；“都要申请”要求确认。终端需首次明确授权，可选择“允许此工作区使用终端，不再询问”，之后该工作区跨任务生效，可在设置撤销。终端不是文件系统沙箱。
4. 模型回复和处理记录按对话顺序显示；执行记录、终端输出和成果默认折叠，浏览器接管位于右侧执行详情。授权提示支持系统通知和声音（受浏览器通知权限及系统设置影响）。
5. 工具错误会分类为参数、路径、版本冲突、超时、命令退出或其他错误，连同历史发回模型修正。每次开始/继续执行重新计数，默认累计 **3 次**即停止并在对话中请求用户介入，成功调用不清零。计划的“执行保护设置”可调整上限 1–20。权限拒绝和越界不会通过重试绕过。
6. UI 不再把任务标为“失败”。需要介入时显示具体原因；单次工具错误仍保留在执行记录中。模型结束后记录计划内检查结果，由用户验收，不根据历史工具错误自动否定整个成果。

`document.edit` 支持原地修改及写入已有目标，使用 SHA-256 检查和临时文件原子替换；工作区内遵循底部权限模式。文件分页读取、文本搜索、终端、Git、常见文档、浏览器、MCP、技能、记忆、定时任务与可选协作均已接入。具体边界见 [验收矩阵](docs/acceptance.md)。

## 测试与维护

```cmd
python scripts\test.py -q
python -m pip install --target .runtime/formatter -r requirements-dev.txt
format.cmd
format.cmd --check
```

`format.cmd` / `format.cmd --check` 同时覆盖 Python 和前端；`format-web.cmd --check` 可单独检查 TS/TSX、CSS、桌面脚本和前端测试。Python 使用固定版本 Black/isort；前端使用 Prettier 3.5.3，配置见 `.prettierrc.json`。`build.cmd` 和 `pnpm build` 都先执行前端格式检查和 TypeScript 检查，再构建。

网页测试使用独立目录；每次完整测试请指定新的目录以免旧测试会话重名：

```cmd
set "AGENT_DATA=D:\UCL\render\agent\.runtime\my-ui-test"
set "AGENT_PORT=8793"
start.cmd --no-browser
node node_modules\@playwright\test\cli.js test
stop.cmd
```

测试会使用真实临时文件和子进程，模型行为由本地替身驱动，不消耗用户 API。浏览器工具测试需要安装 Chromium：`node node_modules\@playwright\test\cli.js install chromium`。

## 文档入口

- [当前需求和权限边界](docs/requirements.md)
- [架构与维护说明](docs/architecture.md)
- [上下文预算和压缩](docs/context.md)
- [当前验收矩阵及待验证项](docs/acceptance.md)
- [本次自动验证结果](docs/verification.json)

`requirements-source.txt` 保留最初的输入规格供追溯；当前用户确认的需求及上述文档优先。`data/` 是正式数据，包含工作区、记录和备份；`.runtime/`、`dist/`、`release/` 是依赖、验证或构建目录，均不提交 Git。
