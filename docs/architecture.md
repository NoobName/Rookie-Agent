# 当前架构与维护

当前版本：0.8.1。

## 服务和持久化

React → loopback HTTP / SSE → FastAPI → SQLite WAL。Electron 提供窗口、托盘、目录选择、通知与共享服务连接，renderer 禁用 Node 并启用隔离和沙箱。服务仅绑定 127.0.0.1，使用 Bearer、Origin 白名单及桌面身份校验。启动链接通过 fragment 传入本地令牌。

`app.py` 定义接口；`models.py` 是严格请求契约；`store.py` 与 `migration.sql` 管理持久数据和迁移；`engine.py` 管理单任务队列、模型回合与工具调度；`tools.py` 和专用模块执行真实动作；`policy.py` 独立检查权限。前端在 `apps/web/src`，桌面入口在 `apps/desktop/main.cjs`。

每次工具调用写入 calls、call_meta，模型工具批次通过 model_turns/call_turns 关联原始 provider ID。完整请求/工具结果按合法 assistant/tool 顺序重建。事件日志支持刷新恢复与时间线定位。正在执行的操作中断后标记 interrupted，用户必须审查是否重试或跳过；尚未派发的操作为 not_executed。启动器不按端口猜测 PID 强杀进程。

## 工具并发、检索与子 Agent

单主任务队列内，连续且已获准的只读操作最多 4 路并发。写入、进程和需要申请授权的操作是顺序屏障；返回按原始工具调用顺序排列。calls/call_meta/call_turns 登记合并事务，文件读取/检索在线程执行。暂停取消会等待在途读取收尾，不继续派发。

`delegation.py` 的同模型检索子 Agent 和 `collaboration.py` 的跨模型咨询分开。子 Agent 独立维护 assistant/tool 消息，工具记录标记 `phase=delegation`，从父上下文排除，但 API/界面仍可查看。父任务只接收摘要、出处、未完成标记。子请求计入父任务账单和预算；子循环有独立错误计数和轮数上限，暂停取消跟随父任务。

`code_search.py` 实现正则/glob/上下文行搜索，正则匹配设超时；符号索引按文件路径、修改时间和大小复用，重启后按需重建。Python AST 返回限定名、定义范围，其他语言为词法声明定位。

## 数据库一致性与后续并发

Store 不再共享跨线程 SQLite 连接。每次独立操作拥有自己的连接；同步事务在当前线程复用连接，嵌套事务使用 SAVEPOINT，内部 `run()` 不会提前提交。WAL 保留并发读，15 秒 busy timeout 允许写事务排队。任务状态与事件、计划修订、任务创建、记忆与 FTS、删除操作均有原子单元；并发计数、不可见未提交写入、嵌套回滚和记忆回滚有真实 SQLite 测试。

事务范围内禁止 await、网络调用和子进程等待。当前调度仍是单执行器；数据库已可被后台线程安全使用，这不等于已经开放多任务并发写文件。后续并发执行必须再引入任务归属、工作区/路径互斥和任务修订冲突检查，不能只增加 worker 数量。

`/health` 仅返回存活与版本，不生成认证令牌的签名。桌面发现使用独立、每次启动随机生成的 256 位 `discovery.key`；该密钥不能用作 API Bearer。Origin/Host 检查覆盖两条路由。CSP 和 Vite 代理均采用 `AGENT_PORT`。

## 前端结构

`main.tsx` 仅挂载 App；`api.ts` 统一认证请求；`useWorkbench.ts` 管理工作台数据与交互；Sidebar、PlanEditor、Composer、Inspector 分别负责主要视图。会话、项目、任务、消息、调用、Bootstrap 有共享 TypeScript 契约；事件动态负载采用 unknown。主路径、授权卡、扩展和连接表单已移除显式 any；其他旧组件仍需渐进完善类型，不宣称全库零 any。

## 错误反馈和结束状态

`tool_errors.py` 将参数错误、文件缺失、权限、版本冲突、超时、退出码和其他工具错误转换为 `error_info`。记录包括 type、message、exit_code、details、suggestion、requires_user；输出摘要限长，原始结果仍存储。参数不合法也生成工具结果而不是直接抛掉整个回合。

每次 run 开始记录 tool_error_cycle；执行工具出错递增累计计数并记录 tool_error。计数少于 `guardrails.max_tool_errors` 时，下一次请求携带当前任务、对话上下文和工具历史，让模型自行修正。默认上限 3，可设 1–20，成功调用不清零。达到上限即进入 waiting_for_user，后续尚未派发工具停止，当前并发批次中已启动的只读调用可能完成且保留结果；用户显式继续才开始新的计数周期。权限受限可提前停止，拒绝授权不当作可绕过的修复机会。

429、5xx、网络超时按 provider_retries 有限重试，重试发生在工具派发前。API 协议错误和服务异常保留内部 failed 状态用于审计，UI 映射为“需要你处理”并显示中止原因；单个工具的 failed 仅表示该工具实际报错。无进展重复、步数或预算保护另行请求用户处理。

模型返回最终答复后运行计划中的 checks 并记录证据，不根据历史错误做整体失败判定，也不再触发旧 repair_rounds 修复循环（字段仅为旧计划兼容保留）。机器检查与用户验收分开；用户接受后 completed。没有工具的普通问答可直接结束。

`progress.py` 使用最多 64 条成功调用的内存窗口，复用读写结果中的 SHA-256，并排除时间戳、调用 ID 等噪音。重复观察和文件版本循环默认第 3 次向模型提示，模型实际收到提示后仍达到第 5 次才暂停；不同版本的持续修改只提醒。写入使旧的读取计数失效。检测不调用模型、不重新读取文件；这仍是启发式判断，不能识别所有语义无效修改。

主任务 `max_steps` 默认 160、范围 1–1000，计数单位是模型回合。状态事件持久保存 `reason` 并通过任务的 `stop_reason` 返回：step_limit / no_progress / tool_error_limit / permission_required / budget_limit。额度耗尽支持 `/continue`，保留计划版本和已执行历史；其他原因仍需审查后继续。旧任务显式额度保持原值。

## 授权、文档与扩展

文件路径经 resolve/commonpath 检查，包含符号链接或 junction 越界检查。工作区模式自动批准文件读写、文档处理/修改、web.fetch、web.search 和已声明的只读子任务；ask 模式需授权。终端可记录显式授予的工作区权限，撤销后立即重新申请。其他复用规则绑定完整参数、作用域、期限和撤销状态。

`document_edit.py` 先校验源/目标 SHA-256，再写同目录临时文件、重新检查版本和路径，最后原子替换。失败清理临时文件；同路径和已有输出均支持。DOCX/XLSX/PDF/文本的修改能力有明确格式边界，不等价于通用 Office 编辑器。

MCP 模型契约仅接受已登记的 `server_id`、工具名和参数，不接受 command/args/url/transport。启动连接只从用户保存的注册表解析；空 ID、额外连接字段、禁用服务与修订不符都会拒绝。配置修订绑定授权快照，凭据执行时解析。浏览器人工接管暂停任务，保持独立 profile。技能以快照加入任务，不直接赋予权限。记忆支持编辑历史、作用域检索与删除；定时调度仅在本地服务运行时入队，执行时再次检查授权。协作子模型只返回建议，主执行器保持单一写入路径。

上下文详见 [context.md](context.md)，验证状态见 [acceptance.md](acceptance.md)。

## 开发约定

Python 使用 4 空格缩进，Black 100 列、isort black profile。前端采用 Prettier 3.5.3（100 列）。执行 `format.cmd` 同时格式化两种语言，`format.cmd --check` 只检查；`format-web.cmd` 可单独执行前端格式化；依赖见 requirements-dev.txt。格式化脚本使用单进程，避免 Windows/Conda 的进程池启动差异。行为变更优先增加真实文件、进程或 HTTP 协议回归，不使用仅验证成功字符串的测试代替实际产物检查。

## 桌面运行目录与安装

本机实测官方原始 Electron 和打包 EXE 在工作区目录内出现 0x80000003；同一原始二进制复制到普通用户临时目录后 `--version` 成功，实际用户安装后的桌面 smoke 也成功。证据定位到目录相关的 Windows 沙箱兼容问题，未进一步断言某一条 ACE 是根因。Electron 上游也有目录 ACL 引起沙箱初始化退出的记录：[官方问题 #51761](https://github.com/electron/electron/issues/51761)。

`desktop-runtime.cjs` 按版本和二进制哈希将开发运行时复制到普通用户应用目录，并做启动探测；`install-desktop.cmd` 校验复制后的安装器再启动。Windows 安装包自带后端，最终验证运行用户目录中的成品，而不是仅验证打包命令退出码。所有路径保留 sandbox=true、contextIsolation=true、nodeIntegration=false；回归明确禁止 --no-sandbox。
