import React from 'react';
import type { Task, Session, PlanResponse, Skill, Project } from '../../../packages/contracts';
import type { Workbench } from './useWorkbench';
import { request } from './api';
import { labels } from './workbenchDefaults';
import { BrowserControl } from './BrowserControl';

export function Inspector({
  events,
  calls,
  input,
  task,
  compaction,
  act,
}: Pick<Workbench, 'events' | 'calls' | 'input' | 'task' | 'compaction' | 'act'>) {
  return (
    <aside className="inspector">
      <h3>执行详情</h3>
      {compaction && (
        <details className="context-compaction">
          <summary>
            上下文压缩记录 · {Number(compaction.before_tokens).toLocaleString()} →{' '}
            {Number(compaction.input_tokens).toLocaleString()} token（估算）
          </summary>
          <p>本地结构化压缩，不调用额外模型。完整执行记录仍保留；当前目标与验收条件不压缩。</p>
          <pre>
            {String(compaction.checkpoint || '长工具结果已保留首尾摘要，原始内容见执行详情。')}
          </pre>
        </details>
      )}{' '}
      {task && (
        <BrowserControl key={'browser-' + task.id} task={task} request={request} act={act} />
      )}
      <div className="section-label">当前任务</div>
      <p>
        {task?.stop_reason === 'step_limit'
          ? '本轮额度已用完，可继续'
          : task?.stop_reason === 'no_progress'
            ? '需要调整策略'
            : task
              ? labels[task.state]
              : '尚未选择任务'}
      </p>
      <div className="section-label">工具日志与文件差异</div>
      {calls.map((c) => (
        <details key={c.id}>
          <summary>
            {c.tool} · {c.status}
          </summary>
          <pre>{c.result?.diff || JSON.stringify(c.result || c.args, null, 2)}</pre>
        </details>
      ))}
      <details>
        <summary>实时终端输出（点击展开）</summary>
        <pre>
          {events
            .filter((e) => ['stdout', 'stderr', 'text'].includes(e.type))
            .slice(-30)
            .map((e) => e.payload.text)
            .join('') || '暂无输出'}
        </pre>
      </details>
      <div className="section-label">消耗</div>
      {events
        .filter((e) => e.type === 'usage')
        .map((e) => (
          <p key={e.id} className="muted">
            输入 {Number(e.payload.input)} / 输出 {Number(e.payload.output)}
            <br />
            {e.payload.estimated ? '估算 token · ' : ''}费用{' '}
            {e.payload.cost == null ? '未知' : String(e.payload.cost)}
          </p>
        ))}
      <p className="footnote">执行证据保存在本机 SQLite。刷新界面不会重新派发任务。</p>
    </aside>
  );
}
