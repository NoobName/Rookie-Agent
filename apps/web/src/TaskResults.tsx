import React, { useEffect, useState } from 'react';

export function TaskResults({
  tid,
  revision,
  state,
  callCount,
  request,
  download,
}: {
  tid: string;
  revision: number;
  state: string;
  callCount: number;
  request: (path: string) => Promise<any>;
  download: (path: string) => void;
}) {
  const [result, setResult] = useState<any>(null),
    [preview, setPreview] = useState<any>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    let live = true;
    setResult(null);
    setPreview(null);
    setError('');
    request(`/tasks/${tid}/result`)
      .then((r) => {
        if (live) setResult(r);
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [tid, revision, state, callCount]);
  async function open(path: string) {
    setLoading(true);
    setError('');
    setPreview(null);
    try {
      setPreview(await request(`/tasks/${tid}/preview?path=${encodeURIComponent(path)}`));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  function exportReport() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = `task-result-${tid}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (!result)
    return error ? (
      <p role="alert" className="error">
        {error}
      </p>
    ) : null;
  const u = result.usage;
  return (
    <section className="result task-results" aria-label="任务成果">
      <div className="row">
        <h3>任务成果</h3>
        <button onClick={exportReport}>导出执行摘要</button>
      </div>
      <p className="muted">
        累计 {u.requests} 次已记录响应 · 输入 {u.input_tokens} / 输出 {u.output_tokens} token
        {u.estimated ? '（含估算）' : ''} ·{' '}
        {u.unknown_cost_requests
          ? `费用未完整配置（${u.unknown_cost_requests} 次未知）`
          : `费用 ${u.known_cost.toFixed(6)}`}
      </p>
      <p>计划交付：{result.planned_deliverables.join('；') || '未填写'}</p>
      {!result.artifacts.length && (
        <p className="muted">
          尚无工具登记的文件产物。终端生成的文件可能未登记，请结合执行记录检查。
        </p>
      )}
      {result.artifacts.map((a: any) => (
        <div className="artifact-row" key={a.path}>
          <div>
            <strong>{a.path}</strong>
            <small>{a.available ? `${a.size} 字节 · ${a.tool}` : '文件已不存在或无法访问'}</small>
          </div>
          <div>
            <button disabled={!a.available || loading} onClick={() => open(a.path)}>
              预览
            </button>{' '}
            <button disabled={!a.available} onClick={() => download(a.path)}>
              下载
            </button>
          </div>
        </div>
      ))}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {preview && (
        <div className="artifact-preview">
          <div className="row">
            <b>{preview.path}</b>
            <button onClick={() => setPreview(null)}>关闭预览</button>
          </div>
          <p className="muted">
            {preview.detail}
            {preview.truncated ? ' 仅展示前 64 KiB。' : ''}
          </p>
          {preview.kind === 'text' && <pre>{preview.text}</pre>}
        </div>
      )}
      <small>预览和下载读取当前文件。摘要包含工作区路径及验收信息，请确认后再分享。</small>
    </section>
  );
}
