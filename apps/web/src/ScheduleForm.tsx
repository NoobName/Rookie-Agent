import React, { useState } from 'react';
export function ScheduleForm({ task, sid, request, act, onSaved }: any) {
  const localDate = (ms: number) => {
    const d = new Date(ms);
    return new Date(ms - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };
  const [kind, setKind] = useState('reminder'),
    [name, setName] = useState('本地提醒'),
    [next, setNext] = useState(localDate(Date.now() + 3600000)),
    [until, setUntil] = useState(localDate(Date.now() + 86400000)),
    [interval, setInterval] = useState(''),
    [missed, setMissed] = useState('skip');
  return (
    <section className="result">
      <h3>创建本地提醒或定时任务</h3>
      <label>
        类型
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="reminder">仅通知提醒</option>
          <option value="task">执行当前任务计划</option>
        </select>
      </label>
      <label>
        名称 / 提醒内容
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="two">
        <label>
          下次执行（本机时间）
          <input type="datetime-local" value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
        <label>
          授权截止（本机时间）
          <input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
      </div>
      <label>
        重复间隔（分钟，留空仅一次）
        <input
          type="number"
          min="1"
          value={interval}
          onChange={(e) => setInterval(e.target.value)}
        />
      </label>
      <label>
        错过时间后
        <select value={missed} onChange={(e) => setMissed(e.target.value)}>
          <option value="skip">跳过本次</option>
          <option value="once">恢复后补一次</option>
        </select>
      </label>
      <p>
        本地服务必须运行。时区：{Intl.DateTimeFormat().resolvedOptions().timeZone}
        。定时任务仍需有效工具授权；不会在关机时云端执行。
      </p>
      <button
        disabled={!name || !next || !until || (kind === 'task' && !task)}
        onClick={() =>
          act(async () => {
            const nextRun = new Date(next).getTime() / 1000,
              expires = new Date(until).getTime() / 1000;
            if (expires <= nextRun) throw new Error('授权截止须晚于下次执行');
            await request('/schedules/new', 'PUT', {
              name,
              kind,
              session_id: kind === 'task' ? sid : '',
              spec: kind === 'task' ? task.spec : null,
              next_run: nextRun,
              authorized_until: expires,
              interval_seconds: interval ? Number(interval) * 60 : null,
              timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              missed,
              enabled: true,
            });
            await onSaved();
          })
        }
      >
        保存并授权调度
      </button>
    </section>
  );
}
