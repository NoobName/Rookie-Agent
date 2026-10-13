import React from 'react';
import type { Task, Session, PlanResponse, Skill, Project } from '../../../packages/contracts';
import type { Workbench } from './useWorkbench';
import { request } from './api';
import { labels } from './workbenchDefaults';
import { CheckEditor } from './Verification';

export function PlanEditor({
  boot,
  input,
  busy,
  provider,
  spec,
  editing,
  questions,
  mode,
  collaboration,
  setView,
  setSpec,
  setQuestions,
  act,
  session,
  savePlan,
}: Pick<
  Workbench,
  | 'boot'
  | 'input'
  | 'busy'
  | 'provider'
  | 'spec'
  | 'editing'
  | 'questions'
  | 'mode'
  | 'collaboration'
  | 'setView'
  | 'setSpec'
  | 'setQuestions'
  | 'act'
  | 'session'
  | 'savePlan'
>) {
  return (
    <div className="content">
      <h1>{editing ? '修改任务计划' : '把需求变成可执行计划'}</h1>
      <p className="muted">确认目标、交付物与权限。未填写验收条件时，任务会等待补充。</p>
      <button
        disabled={busy || !spec.goal}
        onClick={() =>
          act(async () => {
            const s = await session();
            const p = await request<PlanResponse>(`/sessions/${s}/plan`, 'POST', {
              content: spec.goal + '\n' + spec.context,
              provider: spec.provider,
            });
            setQuestions(p.questions || []);
            if (p.goal)
              setSpec({
                ...spec,
                goal: p.goal,
                deliverables: p.deliverables,
                acceptance: p.acceptance,
                plan: p.plan,
                tools: p.tools,
              });
          })
        }
      >
        让当前模型完善计划
      </button>
      {questions.length > 0 && (
        <div className="notice">
          <b>需要补充</b>
          {questions.map((q, i) => (
            <p key={i}>{q}</p>
          ))}
          <small>请将回答填写在上下文，再次完善计划。</small>
        </div>
      )}
      <label>
        目标
        <textarea value={spec.goal} onChange={(e) => setSpec({ ...spec, goal: e.target.value })} />
      </label>
      <label>
        工作区目录
        <input
          value={spec.workspace}
          onChange={(e) => setSpec({ ...spec, workspace: e.target.value })}
          placeholder="演示可留空，自动创建独立目录；真实任务输入现有路径"
        />
      </label>
      {window.desktop && (
        <button
          onClick={() =>
            act(async () => {
              const p = await window.desktop?.pickDirectory();
              if (p) setSpec({ ...spec, workspace: p });
            })
          }
        >
          选择本地目录
        </button>
      )}
      <div className="two">
        <label>
          交付物（每行一项）
          <textarea
            value={spec.deliverables.join('\n')}
            onChange={(e) => setSpec({ ...spec, deliverables: e.target.value.split('\n') })}
          />
        </label>
        <label>
          验收条件（每行一项）
          <textarea
            value={spec.acceptance.join('\n')}
            onChange={(e) => setSpec({ ...spec, acceptance: e.target.value.split('\n') })}
          />
        </label>
      </div>
      <CheckEditor spec={spec} onChange={setSpec} />
      <label>
        执行计划
        <textarea
          value={spec.plan.join('\n')}
          onChange={(e) => setSpec({ ...spec, plan: e.target.value.split('\n') })}
        />
      </label>
      <label>
        上下文与补充说明
        <textarea
          value={spec.context}
          onChange={(e) => setSpec({ ...spec, context: e.target.value })}
        />
      </label>
      <label>
        权限模式
        <select
          aria-label="权限模式"
          value={spec.mode}
          onChange={(e) => setSpec({ ...spec, mode: e.target.value as 'ask' | 'workspace' })}
        >
          <option value="ask">逐次询问</option>
          <option value="workspace">工作区内自动批准读取和写入</option>
        </select>
      </label>
      <p className="notice">
        终端可访问工作区外的资源，并非系统沙箱；可在首次询问时批准此工作区终端，直到撤销；也可只批准单次或相同参数操作。覆盖已有文件需要读取并匹配版本。
      </p>
      <label>
        模型
        <select
          value={spec.provider}
          onChange={(e) => setSpec({ ...spec, provider: e.target.value })}
        >
          {boot.providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={spec.collaboration}
          onChange={(e) => setSpec({ ...spec, collaboration: e.target.checked })}
        />{' '}
        启用多模型只读咨询（额外消耗，默认关闭）
      </label>
      {spec.collaboration && (
        <label>
          角色映射（每行 角色=provider ID）
          <textarea
            defaultValue={Object.entries(spec.collaboration_mapping || {})
              .map(([k, v]) => `${k}=${v}`)
              .join('\n')}
            onBlur={(e) =>
              setSpec({
                ...spec,
                collaboration_mapping: Object.fromEntries(
                  e.target.value
                    .split('\n')
                    .filter((l) => l.includes('='))
                    .map((l) => l.split('=', 2)),
                ),
              })
            }
          />
        </label>
      )}
      <div className="two">
        <label>
          token 提醒（留空不提醒）
          <input
            type="number"
            min="1"
            value={spec.token_reminder || ''}
            onChange={(e) =>
              setSpec({
                ...spec,
                token_reminder: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
        <label>
          硬 token 预算（默认无限制）
          <input
            type="number"
            min="1"
            value={spec.hard_token_budget || ''}
            onChange={(e) =>
              setSpec({
                ...spec,
                hard_token_budget: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
      </div>
      <div className="two">
        <label>
          任务费用提醒（留空关闭）
          <input
            type="number"
            min="0"
            step="any"
            value={spec.cost_reminder ?? ''}
            onChange={(e) =>
              setSpec({
                ...spec,
                cost_reminder: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
        <label>
          任务费用硬预算（留空无限制）
          <input
            type="number"
            min="0"
            step="any"
            value={spec.hard_cost_budget ?? ''}
            onChange={(e) =>
              setSpec({
                ...spec,
                hard_cost_budget: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
      </div>
      <label>所需工具</label>
      <div className="checks">
        {boot.tools.map((tool: string) => (
          <label key={tool}>
            <input
              type="checkbox"
              checked={spec.tools.includes(tool)}
              onChange={(e) =>
                setSpec({
                  ...spec,
                  tools: e.target.checked
                    ? [...spec.tools, tool]
                    : spec.tools.filter((t) => t !== tool),
                })
              }
            />
            {tool}
          </label>
        ))}
      </div>
      <button className="primary" disabled={busy || !spec.goal} onClick={() => act(savePlan)}>
        保存计划
      </button>{' '}
      <button onClick={() => setView('chat')}>返回</button>
    </div>
  );
}
