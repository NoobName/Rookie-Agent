import React, { useState, useEffect } from 'react';
export function Memory({ act, request }: any) {
  const [items, setItems] = useState<any[]>([]),
    [text, setText] = useState(''),
    [scope, setScope] = useState('personal'),
    [id, setId] = useState('new'),
    [q, setQ] = useState(''),
    [kind, setKind] = useState('explicit'),
    [auto, setAuto] = useState(false),
    [history, setHistory] = useState<any[]>([]);
  const refresh = async () => setItems(await request('/memories?q=' + encodeURIComponent(q)));
  useEffect(() => {
    let live = true;
    request('/memories?q=' + encodeURIComponent(q))
      .then((r: any) => {
        if (live) setItems(r);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [q]);
  useEffect(() => {
    request('/memory-settings').then((r: any) => setAuto(r.auto_summary));
  }, []);
  async function exportAll() {
    const data = await request('/memories/export');
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'agent-memories.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="content">
      <h1>可见、可编辑的记忆</h1>
      <p className="muted">
        个人范围使用
        personal，项目范围使用工作区绝对路径。删除会移除记忆、其版本历史和检索索引；原任务审计、既有备份及已发送的聊天内容保留。
      </p>
      <label>
        <input
          type="checkbox"
          checked={auto}
          onChange={(e) => {
            const enabled = e.target.checked;
            act(async () => {
              await request('/memory-settings', 'PUT', { auto_summary: enabled });
              setAuto(enabled);
            });
          }}
        />{' '}
        接受任务结果后自动保存项目验收摘要（默认关闭）
      </label>
      <p className="muted">
        只记录已接受的目标、交付物与检查结果，不让模型推断个人事实。关闭后不再创建摘要，已有记忆可逐项删除。
      </p>
      <button onClick={() => act(exportAll)}>导出全部记忆</button>
      <input
        aria-label="搜索记忆"
        placeholder="搜索记忆"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <label>
        范围
        <input value={scope} onChange={(e) => setScope(e.target.value)} />
      </label>
      <label>
        记忆类型
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="explicit">明确事实</option>
          <option value="inferred">模型推断（需核实）</option>
          <option value="unconfirmed">待确认</option>
        </select>
      </label>
      <label>
        记忆内容
        <textarea value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <button
        className="primary"
        disabled={!text.trim()}
        onClick={() =>
          act(async () => {
            await request('/memories/' + id, 'PUT', { scope, content: text, kind });
            setText('');
            setId('new');
            setHistory([]);
            await refresh();
          })
        }
      >
        保存记忆
      </button>
      {items.map((m) => (
        <div className="result" key={m.id}>
          <small>
            {m.scope} · {m.kind} · 来源：{m.source} · {new Date(m.updated * 1000).toLocaleString()}
          </small>
          <p>{m.content}</p>
          <button
            onClick={() => {
              setId(m.id);
              setScope(m.scope);
              setText(m.content);
              setKind(m.kind);
            }}
          >
            编辑
          </button>{' '}
          <button
            onClick={() =>
              act(async () => {
                setHistory(await request(`/memories/${m.id}/history`));
              })
            }
          >
            版本历史
          </button>{' '}
          <button
            onClick={() =>
              act(async () => {
                await request('/memories/' + m.id, 'DELETE');
                setHistory([]);
                if (id === m.id) {
                  setId('new');
                  setText('');
                }
                await refresh();
              })
            }
          >
            删除
          </button>
        </div>
      ))}
      {history.length > 0 && (
        <section>
          <h2>编辑前的历史版本</h2>
          {history.map((h) => (
            <pre key={h.id}>{h.snapshot.content}</pre>
          ))}
        </section>
      )}
    </div>
  );
}
