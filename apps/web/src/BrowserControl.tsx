import React, { useState } from 'react';
export function BrowserControl({ task, request, act }: any) {
  const [status, setStatus] = useState('');
  if (!task.spec.tools.includes('browser.action')) return null;
  const enabled = [
    'planned',
    'running',
    'verifying',
    'awaiting_approval',
    'waiting_for_user',
    'paused',
  ].includes(task.state);
  return (
    <section className="result">
      <h3>浏览器接管</h3>
      <p>
        在独立浏览器中登录或处理验证码。接管会暂停任务；结束接管后仍需审查计划并继续，不会自动提交表单。
      </p>
      <button
        disabled={!enabled}
        onClick={() =>
          act(async () => {
            const r = await request(`/tasks/${task.id}/browser`, 'POST', { human: true });
            setStatus(r.detail);
          })
        }
      >
        暂停并打开浏览器接管
      </button>{' '}
      <button
        disabled={!enabled}
        onClick={() =>
          act(async () => {
            const r = await request(`/tasks/${task.id}/browser`, 'POST', { human: false });
            setStatus(r.detail);
          })
        }
      >
        结束接管
      </button>
      <p role="status">{status}</p>
    </section>
  );
}
