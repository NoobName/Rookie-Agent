import React, { useEffect, useState } from 'react';
export function Usage({ request, act }: any) {
  const [channel, setChannel] = useState('chromium');
  const [data, setData] = useState<any>(null),
    [limits, setLimits] = useState<any>({}),
    [error, setError] = useState('');
  async function refresh() {
    const d = await request('/usage');
    setData(d);
    setLimits(d.limits);
  }
  useEffect(() => {
    refresh().catch((e: any) => setError(String(e)));
    request('/browser-settings')
      .then((r: any) => setChannel(r.channel))
      .catch((e: any) => setError(String(e)));
  }, []);
  return (
    <section>
      <h2>浏览器与通知</h2>
      <label>
        独立浏览器
        <select value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="chromium">Playwright Chromium</option>
          <option value="msedge">本机 Microsoft Edge</option>
          <option value="chrome">本机 Chrome</option>
        </select>
      </label>
      <button onClick={() => act(() => request('/browser-settings', 'PUT', { channel }))}>
        保存浏览器选择
      </button>
      <p>
        使用独立 profile，不读取日常浏览器资料；切换会关闭 Agent 浏览器会话。本机可见 Chromium
        无法启动时可选择 Edge。
      </p>
      <button
        onClick={async () => {
          if ('Notification' in window) {
            const result = await Notification.requestPermission();
            setError(result === 'granted' ? '浏览器通知已启用' : '浏览器未授予通知权限');
          }
        }}
      >
        启用网页通知
      </button>
      <h2>累计用量与预算</h2>
      {error && <p className="error">{error}</p>}
      <p>
        按本地账本累计，删除会话不会清零。默认无上限。费用按配置单价计算；不同货币请先统一单价单位。
      </p>
      {data && (
        <p>
          输入 {data.total.input_tokens} / 输出 {data.total.output_tokens} token · 已记录{' '}
          {data.total.requests} 次响应 · 已知费用 {data.total.known_cost} · 未知费用{' '}
          {data.total.unknown_cost_requests || 0} 次 · 含估算 {data.total.estimated_requests} 次
        </p>
      )}
      <div className="two">
        {[
          ['token_reminder', '累计 token 提醒'],
          ['cost_reminder', '累计费用提醒'],
          ['hard_tokens', '累计 token 硬上限'],
          ['hard_cost', '累计费用硬上限'],
        ].map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              type="number"
              min="0"
              step={key.includes('cost') ? 'any' : '1'}
              value={limits[key] ?? ''}
              onChange={(e) =>
                setLimits({ ...limits, [key]: e.target.value ? Number(e.target.value) : null })
              }
            />
          </label>
        ))}
      </div>
      <p className="muted">
        留空表示关闭。达到硬上限后阻止下一模型请求，在途请求可能超额。存在历史未知费用时，硬费用预算会阻止请求。提高或关闭上限后可继续。
      </p>
      <button
        onClick={() =>
          act(async () => {
            await request('/usage/limits', 'PUT', limits);
            await refresh();
          })
        }
      >
        保存累计预算
      </button>{' '}
      <button onClick={() => act(refresh)}>刷新用量</button>
      {data?.providers.map((p: any) => (
        <p key={p.provider}>
          {p.provider} · {p.requests} 次 · 输入 {p.input_tokens} / 输出 {p.output_tokens} ·{' '}
          {p.unknown_cost_requests ? '费用含未知' : `费用 ${p.known_cost}`}
        </p>
      ))}
    </section>
  );
}
