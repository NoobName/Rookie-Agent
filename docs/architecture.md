# 架构

React → loopback HTTP / 可恢复 SSE → FastAPI → SQLite WAL。
Electron 只负责安全窗口和原生目录选择；连接同一后端，窗口关闭不杀共享后端。
后端单个执行器，任务间串行。每次动作先持久化请求，经过统一策略，再执行并持久化结果。
暂停/取消作用于任务；重启把运行中任务改为 paused，人工审查后创建新的继续回合，不重放旧调用。

数据库版本 2 增加独立运行元数据：计划 revision、验收报告、调用阶段/工作流/步骤、用户补充、恢复决定、期限授权规则和模型请求尝试记录。原 tasks/calls 列不变，可兼容原数据库。尚未派发的调用记为 not_executed；已派发后中断的调用记为 interrupted，未审查前不能入队。

每次模型请求从持久记录重建配对的 assistant/tool 消息，限制上下文体积；旧日志保留本地审计，不全部发送。文件/工具证据不进入 system 角色。暂时网络错误、429 与服务端错误仅在模型响应完整返回、工具尚未派发前有限重试；格式错误不重试。请求失败的用量可能未知。

模型完成后执行用户计划中的 checks，由相同 PolicyEngine 授权、Tools 执行并保存证据。失败交回主模型，受 repair_rounds 限制；实际执行成功可解除同类操作的历史失败。人工条件和机器条件分开呈现，只有用户接受才 completed。计划编辑/补充会清除旧验证版本。Scripted 按工作流步骤恢复，不依赖验证调用数量推算位置。

授权规则绑定用户、任务或规范化工作区、工具、完整参数、到期时间和撤销状态。当前只支持参数完全匹配，不开放目录通配或任意终端命令通配。前端操作与轮询使用更新版本防止旧授权卡片覆盖新状态；后端仍独立验证请求是否有效。

CMD 启动器只使用 Python 标准库，验证本机健康状态及数据目录令牌。停止使用认证的优雅关闭接口，执行中/排队时拒绝停止；不按端口猜测 PID 强制结束进程。AGENT_PORT 用于隔离验收服务，正式构建网页使用同源 API。
OpenAI-compatible 和 Scripted Provider 独立。真实密钥使用 keyring；配置只存随机凭据引用。
工作区文件操作使用 resolve/commonpath 并拒绝越界；shell 被明确视为非隔离执行。
本地服务绑定 127.0.0.1，Bearer 认证、Origin 白名单，静态网页不含 token。启动器用 URL fragment 交付会话令牌。

官方资料核验：
- https://fastapi.tiangolo.com/advanced/events/ （lifespan）
- https://www.electronjs.org/docs/latest/tutorial/security （contextIsolation、sandbox）
- https://platform.openai.com/docs/api-reference/chat/create （兼容协议）
- https://github.com/modelcontextprotocol/python-sdk （锁定 1.x API，stdio/Streamable HTTP）

选择成熟锁定版本而非无界 latest；后续升级必须重跑验收。前端只渲染文本，不执行模型返回 HTML。

0.3.0：memory_history 记录编辑前快照；memories、history、FTS 更新/删除使用 SQLite 事务。检索对输入做字面 FTS 转义并提供中文子串匹配；上下文注入限定 personal 或当前工作区，暂无向量检索。auto_memory 默认 false，只在用户接受任务后生成确定性事实摘要。技能模板经 schema 校验，用户选用后把实际内容快照复制到任务上下文，不直接调度工具。富文本组件只构建 React 文本/代码/列表及 HTTP(S) 链接，不使用 innerHTML。
