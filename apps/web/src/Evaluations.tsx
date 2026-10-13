import React, { useEffect, useState } from 'react';
export function Evaluations({ providers, request, act, onTask }: any) {
  const [provider, setProvider] = useState(
      providers.find((p: any) => p.id !== 'scripted')?.id || '',
    ),
    [rows, setRows] = useState<any[]>([]),
    [error, setError] = useState('');
  useEffect(() => {
    request('/evaluations')
      .then(setRows)
      .catch((e: any) => setError(String(e)));
  }, []);
  return (
    <section>
      <h2>可重复能力评测</h2>
      <p>
        每次创建一个待审查任务。开始后会产生模型费用，代码执行仍需授权。记录单次实际检查，不据此推断通用排名。
      </p>
      {error && <p className="error">{error}</p>}
      <label>
        评测模型
        <select value={provider} onChange={(e) => setProvider(e.target.value)}>
          {providers
            .filter((p: any) => p.id !== 'scripted')
            .map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
      </label>
      {['coding', 'documents'].map((suite) => (
        <button
          disabled={!provider}
          key={suite}
          onClick={() =>
            act(async () => {
              const task = await request('/evaluations', 'POST', { provider, suite });
              onTask(task);
            })
          }
        >
          {suite === 'coding' ? '创建代码功能评测' : '创建文档产物评测'}
        </button>
      ))}
      {rows.map((r) => (
        <p key={r.id}>
          {r.provider} / {r.model} · {r.suite} v{r.version} · 样本 {r.samples} ·{' '}
          {r.machine_passed ? '机器检查通过' : `未通过或尚未完成（${r.state}）`} ·{' '}
          {r.user_accepted ? '已人工接受' : '未人工接受'}
        </p>
      ))}
    </section>
  );
}
