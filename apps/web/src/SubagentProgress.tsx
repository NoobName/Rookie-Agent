import React from 'react';

type Event = { type: string; payload: Record<string, unknown> };
export function SubagentProgress({ events }: { events: Event[] }) {
  const agents = events.filter((event) => event.type === 'subagent_started');
  if (!agents.length) return null;
  return (
    <details className="subagent-progress">
      <summary>子任务 · {agents.length} 个独立上下文</summary>
      {agents.map(({ payload }) => {
        const finished = events.find(
          (event) => event.type === 'subagent_finished' && event.payload.id === payload.id,
        );
        return (
          <div key={String(payload.id)}>
            <p>{String(payload.objective)}</p>
            <p className="muted">
              {finished
                ? `${finished.payload.status === 'succeeded' ? '已返回' : '已停止'} · ${Number(finished.payload.tool_calls || 0)} 次工具调用`
                : '正在检索与分析'}
            </p>
            {finished && <p>{String(finished.payload.output || finished.payload.error || '')}</p>}
          </div>
        );
      })}
    </details>
  );
}
