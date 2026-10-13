import React, { useEffect, useState } from 'react';
import { ActionRequired } from './ActionRequired';
import { FailureReply } from './FailureReply';
import { ExecutionProgress } from './ExecutionProgress';
import { MessageContent } from './MessageContent';
import { TaskResults } from './TaskResults';
import { VerificationReport } from './Verification';

export function conversationStatus(state?: string, busy = false) {
  if (busy || ['running', 'verifying'].includes(state || '')) return '正在进行';
  if (
    [
      'awaiting_approval',
      'waiting_for_user',
      'paused',
      'clarifying',
      'draft',
      'planned',
      'failed',
    ].includes(state || '')
  )
    return '需要用户操作';
  return state ? '上一条输出已结束' : '准备就绪';
}
export function ConversationTimeline({
  messages,
  tasks,
  current,
  events,
  calls,
  request,
  download,
  controls,
}: any) {
  const [history, setHistory] = useState<Record<string, any>>({});
  const [error, setError] = useState('');
  const historyKey = tasks
    .filter((t: any) => t.id !== current?.id)
    .map((t: any) => `${t.id}:${t.updated}:${t.state}`)
    .join('|');
  useEffect(() => {
    let live = true;
    setError('');
    Promise.all(
      tasks
        .filter((t: any) => t.id !== current?.id)
        .map(async (t: any) => [
          t.id,
          {
            events: await request(`/tasks/${t.id}/events`),
            calls: await request(`/tasks/${t.id}/calls`),
          },
        ]),
    )
      .then((entries) => {
        if (live) setHistory(Object.fromEntries(entries));
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [historyKey, current?.id]);
  const ordered = messages
    .map((m: any, i: number) => ({ ...m, created: m.created ?? i }))
    .sort((a: any, b: any) => a.created - b.created);
  const starts = [
    -Infinity,
    ...ordered.filter((m: any) => m.role === 'user').map((m: any) => m.created),
  ];
  const buckets = starts.map((start: number, i: number) => ({
    start,
    end: starts[i + 1] ?? Infinity,
    messages: ordered.filter(
      (m: any) => m.created >= start && m.created < (starts[i + 1] ?? Infinity),
    ),
  }));
  return (
    <>
      {error && <p role="alert">执行记录加载失败：{error}</p>}
      {buckets.map((bucket: any, index: number) => {
        const user = bucket.messages.find((m: any) => m.role === 'user');
        const replies = bucket.messages.filter((m: any) => m.role !== 'user');
        return (
          <React.Fragment key={user?.id || 'initial'}>
            {user && (
              <div className="message user">
                <small>你</small>
                <MessageContent text={user.content} />
              </div>
            )}
            {[...tasks]
              .sort((a: any, b: any) => a.created - b.created)
              .map((t: any) => {
                const data =
                  t.id === current?.id
                    ? { events, calls }
                    : history[t.id] || { events: [], calls: [] };
                const turnEvents = data.events.filter(
                  (e: any) => e.created >= bucket.start && e.created < bucket.end,
                );
                const turnCalls = data.calls.filter(
                  (c: any) => c.created >= bucket.start && c.created < bucket.end,
                );
                const lastTime = Math.max(
                  t.created,
                  ...data.events.map((e: any) => e.created),
                  ...data.calls.map((c: any) => c.created),
                );
                const last = lastTime >= bucket.start && lastTime < bucket.end;
                if (
                  !turnEvents.length &&
                  !turnCalls.length &&
                  !(t.created >= bucket.start && t.created < bucket.end)
                )
                  return null;
                const state = last ? t.state : 'completed';
                return (
                  <div className="turn-execution" key={t.id} data-task-id={t.id}>
                    <ExecutionProgress
                      events={turnEvents}
                      state={state}
                      timing={t.timing}
                      outputAfter={Math.max(-Infinity, ...replies.map((m: any) => m.created))}
                    />
                    {(turnCalls.length > 0 || !t.spec.conversational) && (
                      <details className="turn-records">
                        <summary>执行记录与成果 · {turnCalls.length} 次工具操作</summary>
                        {last && (
                          <>
                            <TaskResults
                              tid={t.id}
                              revision={t.revision ?? 0}
                              state={t.state}
                              callCount={data.calls.filter((c: any) => c.result).length}
                              request={request}
                              download={download}
                            />
                            <VerificationReport task={t} />
                          </>
                        )}
                        {turnEvents
                          .filter((e: any) =>
                            ['state', 'interrupted', 'notification', 'queued'].includes(e.type),
                          )
                          .map((e: any) => (
                            <p className="event-line" key={e.id}>
                              {new Date(e.created * 1000).toLocaleTimeString()} ·{' '}
                              {e.payload.detail ||
                                e.payload.title ||
                                (e.payload.state === 'failed' ? '需要你处理' : e.payload.state) ||
                                '已入队'}
                            </p>
                          ))}
                        {turnCalls
                          .filter((c: any) => c.result)
                          .map((c: any) => (
                            <details className="result" key={c.id}>
                              <summary>
                                {c.tool} ·{' '}
                                {c.status === 'succeeded'
                                  ? '成功'
                                  : c.status === 'failed'
                                    ? '错误'
                                    : c.status}
                              </summary>
                              {c.result.error && <p className="error">{c.result.error}</p>}
                              <pre>
                                {c.result.diff ||
                                  c.result.stdout ||
                                  JSON.stringify(c.result, null, 2)}
                              </pre>
                              {c.result.artifacts?.map((p: string) => (
                                <button key={p} onClick={() => download(p)}>
                                  ↓ {p}
                                </button>
                              ))}
                            </details>
                          ))}
                        {turnEvents
                          .filter(
                            (e: any) => e.type === 'delegation' || e.type === 'delegation_result',
                          )
                          .map((e: any) => (
                            <section key={e.id}>
                              <b>
                                {e.payload.role} · {e.payload.provider}
                              </b>
                              <MessageContent
                                text={e.payload.objective || e.payload.output || ''}
                              />
                            </section>
                          ))}
                      </details>
                    )}
                    {last && <ActionRequired task={t} events={data.events} />}
                    {last && t.id === current?.id && controls}
                  </div>
                );
              })}
            {replies.map((m: any) => (
              <div key={m.id} className={'message ' + m.role}>
                <small>Agent</small>
                <MessageContent text={m.content} />
              </div>
            ))}
            {tasks.flatMap((t: any) => {
              const data = t.id === current?.id ? { events, calls } : history[t.id];
              if (!data) return [];
              const failures = data.events.filter(
                (e: any) => e.type === 'state' && e.payload.state === 'failed',
              );
              const rows = failures.length
                ? failures
                : t.state === 'failed'
                  ? [
                      {
                        id: 'fallback-' + t.id,
                        created: t.updated || t.created,
                        payload: { detail: '执行记录未提供具体原因，请展开本轮执行记录查看。' },
                      },
                    ]
                  : [];
              return rows
                .filter((e: any) => e.created >= bucket.start && e.created < bucket.end)
                .map((e: any) => (
                  <FailureReply key={t.id + '-' + e.id} event={e} calls={data.calls} />
                ));
            })}
          </React.Fragment>
        );
      })}
    </>
  );
}
