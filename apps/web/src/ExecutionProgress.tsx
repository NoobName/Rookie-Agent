import React, { useEffect, useState } from 'react';
import { MessageContent } from './MessageContent';
import { ExecutionPlan } from './ExecutionPlan';
export function ExecutionProgress({
  events,
  state,
  showOutput = true,
  outputAfter = -Infinity,
  timing,
}: any) {
  const [now, setNow] = useState(Date.now());
  const active = ['running', 'verifying'].includes(state);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const reasoning = events
    .filter((e: any) => e.type === 'reasoning')
    .map((e: any) => e.payload.text)
    .join('')
    .slice(-24000);
  const text = events
    .filter((e: any) => e.type === 'text' && e.created > outputAfter)
    .map((e: any) => e.payload.text)
    .join('')
    .slice(-16000);
  const first = events.find((e: any) => e.type === 'model_status');
  const last = events.at(-1);
  const started = timing?.started ?? first?.created;
  const ended = active ? now / 1000 : (timing?.ended ?? last?.created ?? started);
  const seconds = started ? Math.max(0, Math.round(ended - started)) : 0;
  const duration =
    seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
  const label =
    state === 'awaiting_approval'
      ? '等待你的授权'
      : state === 'paused'
        ? '已暂停'
        : active
          ? '正在处理'
          : state === 'failed'
            ? '本轮处理已结束'
            : '已处理';
  return (
    <section className="execution-progress" aria-label="执行过程">
      <ExecutionPlan events={events} />
      <details>
        <summary>
          <span className={active ? 'progress-orbit active' : 'progress-orbit'} aria-hidden="true">
            ◌
          </span>
          <span title="从首次执行到当前或停止时刻的总用时，包含期间等待及暂停">
            {label}
            {started ? ` · 总用时 ${duration}` : ''}
          </span>
          <span className="progress-chevron" aria-hidden="true">
            ›
          </span>
        </summary>
        <div className="progress-body">
          {reasoning ? (
            <MessageContent text={reasoning} />
          ) : (
            <p className="muted">模型未返回可展示的思考内容。</p>
          )}
        </div>
      </details>
      {showOutput && text && (
        <div className="streaming-reply">
          <MessageContent text={text} />
        </div>
      )}
    </section>
  );
}
