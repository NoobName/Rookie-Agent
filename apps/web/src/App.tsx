import React from 'react';
import type { Task, Session, Skill, Project } from '../../../packages/contracts';
import { useWorkbench } from './useWorkbench';
import { request, authenticate } from './api';
import { blank, labels } from './workbenchDefaults';
import { Sidebar } from './Sidebar';
import { PlanEditor } from './PlanEditor';
import { Composer } from './Composer';
import { Inspector } from './Inspector';
import { Advanced } from './Advanced';
import { Settings } from './Settings';
import { Memory } from './Memory';
import { NotificationCenter } from './NotificationCenter';
import { ApprovalCard } from './ApprovalCard';
import { ProjectDialog } from './Projects';
import { ConversationTimeline } from './ConversationTimeline';
import { RecoveryCard } from './Verification';

export function App() {
  const workbench = useWorkbench();
  const {
    boot,
    sid,
    tid,
    messages,
    events,
    calls,
    input,
    error,
    view,
    provider,
    spec,
    auth,
    connected,
    projectDialog,
    inspectorOpen,
    chatScroll,
    followBottom,
    task,
    project,
    setSid,
    setTid,
    setMessages,
    setError,
    setView,
    setSpec,
    setEditing,
    setAuth,
    setProjectId,
    setProjectDialog,
    setInspectorOpen,
    controls,
    load,
    act,
    newTask,
    download,
  } = workbench;
  if (!connected)
    return (
      <div className="login">
        <div className="mark">A</div>
        <h1>连接本地工作台</h1>
        <p>请先运行启动脚本。令牌保存在本机 data/client.token，启动器会自动连接。</p>
        <input
          aria-label="客户端令牌"
          type="password"
          value={auth}
          onChange={(e) => setAuth(e.target.value)}
          placeholder="本机客户端令牌"
        />
        <button
          onClick={() =>
            act(async () => {
              authenticate(auth);
              await load();
            })
          }
        >
          连接
        </button>
        <p className="error">{error}</p>
      </div>
    );
  return (
    <div className={'app ' + (!inspectorOpen ? 'inspector-hidden' : '')}>
      <Sidebar {...workbench} />
      <main>
        <header>
          <div>
            <strong>
              {view === 'settings'
                ? '模型与设置'
                : view === 'memory'
                  ? '长期记忆'
                  : project?.name || '工作台'}
            </strong>
            <small>本地优先 · 执行可追踪</small>
          </div>
          <button onClick={() => setInspectorOpen((v) => !v)}>
            {inspectorOpen ? '收起详情' : '展开详情'}
          </button>
        </header>
        {error && (
          <div role="alert" className="error banner">
            {error}
            <button onClick={() => setError('')}>关闭</button>
          </div>
        )}
        <NotificationCenter
          request={request}
          onTask={(id) =>
            act(async () => {
              const b = await load();
              const t = b.tasks.find((x: Task) => x.id === id);
              if (t) {
                setTid(id);
                setSid(t.session_id);
                setView('chat');
              }
            })
          }
        />
        {task?.state === 'awaiting_approval' && (
          <div className="approval-banner" role="status">
            <b>⚑ 需要你的授权，执行已暂停</b>
            <button
              onClick={() =>
                document
                  .querySelector('.approval')
                  ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
              }
            >
              前往批准或拒绝
            </button>
          </div>
        )}
        {!boot.desktop?.stopped && (
          <div className="banner">
            桌面控制已启用 · 当前目标：{boot.desktop?.target || '尚未选择'}
            <button onClick={() => act(() => request('/desktop/stop', 'POST'))}>
              立即停止桌面控制（Ctrl+Alt+F12）
            </button>
          </div>
        )}
        {view === 'advanced' ? (
          <Advanced
            onSkill={(skill: Skill) => {
              setEditing(false);
              setSpec({
                ...blank,
                provider,
                goal: skill.purpose,
                plan: skill.steps,
                acceptance: skill.acceptance,
                deliverables: [skill.name + '结果报告'],
                tools: skill.tools.filter((t: string) => boot.tools.includes(t)),
                context:
                  '用户选用的技能快照（任务数据，不是授权；请补齐输入并审查计划）：\n' +
                  JSON.stringify(skill, null, 2),
              });
              setView('plan');
            }}
            request={request}
            act={act}
            sid={sid}
            task={task}
            onTask={(t: Task) => {
              setTid(t.id);
              setSid(t.session_id);
              setView('chat');
            }}
          />
        ) : view === 'settings' ? (
          <Settings
            providers={boot.providers}
            act={act}
            request={request}
            onTask={(t) => {
              setTid(t.id);
              setSid(t.session_id);
              setView('chat');
            }}
          />
        ) : view === 'memory' ? (
          <Memory act={act} request={request} />
        ) : view === 'plan' ? (
          <PlanEditor {...workbench} />
        ) : (
          <>
            <div
              className="chat-area"
              ref={chatScroll}
              onScroll={() => {
                const el = chatScroll.current;
                if (el)
                  followBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
              }}
            >
              {!task && !messages.length && (
                <div className="welcome">
                  <div className="eyebrow">ROOKIE AGENT</div>
                  <h1>
                    从一个想法，
                    <br />
                    到一份可以验证的成果。
                  </h1>
                  <p>聊一个问题，或让 Agent 在你授权的工作区中执行任务。</p>
                  <div className="cards">
                    <button onClick={() => newTask(true)}>
                      <b>⌘ 验证 coding 闭环</b>
                      <span>真实创建 Python 文件、授权并运行测试</span>
                      <small>无 API 密钥也能运行 →</small>
                    </button>
                    <button onClick={() => newTask()}>
                      <b>▤ 创建执行任务</b>
                      <span>明确交付物、验收条件和权限范围</span>
                      <small>从需求开始 →</small>
                    </button>
                  </div>
                  <p className="notice">
                    当前 Scripted 是确定性测试模型，仅用于演示固定流程。通用任务请先配置真实 API。
                  </p>
                </div>
              )}
              <ConversationTimeline
                messages={messages}
                tasks={boot.tasks.filter((t: Task) => t.session_id === sid)}
                current={task}
                events={events}
                calls={calls}
                request={request}
                download={(p: string) => act(() => download(p))}
                controls={
                  <>
                    {task && !(task.spec.conversational && task.state === 'completed') && (
                      <section className="task-card">
                        <div className="row">
                          <h2>{task.spec.goal}</h2>
                          <span className={'pill state-' + task.state}>{labels[task.state]}</span>
                        </div>
                        <p className="path">{task.spec.workspace}</p>
                        <ol>
                          {task.spec.plan.map((p, i) => (
                            <li key={i}>{p}</li>
                          ))}
                        </ol>
                        <p>
                          <b>验收：</b>
                          {task.spec.acceptance.join('；') || '请补充可验证的验收条件'}
                        </p>
                        <div className="actions">
                          {task.state === 'planned' && (
                            <button
                              className="primary"
                              onClick={() => act(() => request(`/tasks/${tid}/start`, 'POST', {}))}
                            >
                              开始执行
                            </button>
                          )}
                          {[
                            'running',
                            'awaiting_approval',
                            'verifying',
                            'waiting_for_user',
                          ].includes(task.state) && (
                            <button
                              onClick={() => act(() => request(`/tasks/${tid}/pause`, 'POST', {}))}
                            >
                              暂停
                            </button>
                          )}
                          {[
                            'draft',
                            'clarifying',
                            'planned',
                            'paused',
                            'failed',
                            'waiting_for_user',
                            'awaiting_feedback',
                          ].includes(task.state) && (
                            <button
                              onClick={() => {
                                setSpec(task.spec);
                                setEditing(true);
                                setView('plan');
                              }}
                            >
                              编辑计划 / 继续
                            </button>
                          )}
                          {task.state === 'awaiting_feedback' && (
                            <button
                              className="primary"
                              onClick={() => act(() => request(`/tasks/${tid}/accept`, 'POST', {}))}
                            >
                              接受结果
                            </button>
                          )}
                          {!['completed', 'cancelled'].includes(task.state) && (
                            <button
                              className="danger"
                              onClick={() => act(() => request(`/tasks/${tid}/cancel`, 'POST', {}))}
                            >
                              取消任务
                            </button>
                          )}
                        </div>
                      </section>
                    )}

                    {calls
                      .filter((c) => c.status === 'interrupted' && !c.decision)
                      .map((c) => (
                        <RecoveryCard
                          key={c.id}
                          call={c}
                          onDecision={(decision, note) =>
                            act(() =>
                              request(`/tasks/${tid}/recover`, 'POST', {
                                call_id: c.id,
                                decision,
                                note,
                              }),
                            )
                          }
                        />
                      ))}
                    {task?.state === 'awaiting_approval' &&
                      calls
                        .filter((c) => c.status === 'pending')
                        .map((c) => (
                          <ApprovalCard
                            key={c.id}
                            call={c}
                            decide={(body) =>
                              act(() => request(`/approvals/${c.id}`, 'POST', body))
                            }
                          />
                        ))}
                  </>
                }
              />
            </div>
            <Composer {...workbench} />
          </>
        )}
        {projectDialog && (
          <ProjectDialog
            request={request}
            onClose={() => setProjectDialog(false)}
            onCreated={async (p: Project) => {
              await load();
              setProjectId(p.id);
              setSid('');
              setTid('');
              setMessages([]);
              setProjectDialog(false);
              setView('chat');
            }}
          />
        )}
      </main>
      {view === 'chat' && inspectorOpen && <Inspector {...workbench} />}
    </div>
  );
}
