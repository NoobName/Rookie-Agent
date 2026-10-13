import React, { useEffect, useState } from 'react';
export function MCPServers({ request, act, sid, onTask }: any) {
  const fresh = {
    id: 'my-mcp',
    name: '我的 MCP',
    enabled: true,
    transport: 'stdio',
    command: 'python',
    args: ['examples/mcp_server.py'],
    url: '',
  };
  const [rows, setRows] = useState<any[]>([]),
    [value, setValue] = useState(JSON.stringify(fresh, null, 2)),
    [secret, setSecret] = useState(''),
    [message, setMessage] = useState('');
  async function refresh() {
    setRows(await request('/mcp/servers'));
  }
  useEffect(() => {
    refresh().catch((e) => setMessage(String(e)));
  }, []);
  return (
    <section>
      <h2>MCP 服务列表</h2>
      <p>
        支持多个 stdio / Streamable HTTP 服务。HTTP Bearer 密钥只保存到 Windows 凭据存储；OAuth
        登录尚不支持。
      </p>
      {rows.map((r) => (
        <button
          key={r.id}
          onClick={() => {
            setValue(JSON.stringify(r, null, 2));
            setSecret('');
          }}
        >
          {r.name}
          {r.enabled ? '' : '（停用）'}
        </button>
      ))}
      <button
        onClick={() => {
          setValue(JSON.stringify(fresh, null, 2));
          setSecret('');
        }}
      >
        新建 MCP 服务
      </button>
      <label>
        服务配置 JSON
        <textarea
          style={{ width: '100%', height: 240 }}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <label>
        HTTP Bearer 密钥（留空保留）
        <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} />
      </label>
      <button
        onClick={() =>
          act(async () => {
            const v = JSON.parse(value);
            await request('/mcp/servers/' + v.id, 'PUT', { ...v, ...(secret ? { secret } : {}) });
            setSecret('');
            await refresh();
            setMessage('已保存；配置变化会使旧调用授权失效');
          })
        }
      >
        保存 MCP 服务
      </button>
      <button
        onClick={() =>
          act(async () => {
            const v = JSON.parse(value);
            let session = sid;
            if (!session)
              session = (await request('/sessions', 'POST', { title: 'MCP 服务验证' })).id;
            const task = await request(`/sessions/${session}/tasks`, 'POST', {
              goal: 'MCP 服务连接和工具发现',
              workspace: '',
              provider: 'scripted',
              deliverables: ['真实工具列表与 schema'],
              acceptance: ['连接成功并取得工具列表'],
              tools: ['mcp.call'],
              script: [{ name: 'mcp.call', arguments: { server_id: v.id } }],
            });
            onTask(task);
          })
        }
      >
        创建已保存服务的发现任务
      </button>
      <button
        className="danger"
        onClick={() => {
          const v = JSON.parse(value);
          if (window.confirm('删除此 MCP 配置及凭据？'))
            act(async () => {
              await request('/mcp/servers/' + v.id, 'DELETE');
              await refresh();
              setMessage('已删除服务');
            });
        }}
      >
        删除 MCP 服务
      </button>
      <p role="status">{message}</p>
    </section>
  );
}
