import React, { useEffect, useState } from 'react';
import { MCPServers } from './MCPServers';
import type { Task } from '../../../packages/contracts';
import type { request as apiRequest } from './api';
export function Integrations({
  request,
  act,
  sid,
  onTask,
}: {
  request: typeof apiRequest;
  act: (fn: () => Promise<unknown>) => Promise<void>;
  sid: string;
  onTask: (task: Task) => void;
}) {
  const [kind, setKind] = useState('search'),
    [text, setText] = useState(''),
    [secret, setSecret] = useState(''),
    [status, setStatus] = useState('');
  const templates: Record<string, Record<string, unknown>> = {
    search: {
      enabled: true,
      url: 'https://api.search.brave.com/res/v1/web/search',
      results_path: 'web.results',
      query_parameter: 'q',
      title_field: 'title',
      url_field: 'url',
      snippet_field: 'description',
      header: 'X-Subscription-Token',
      prefix: '',
    },
    email: { enabled: false, host: '', port: 465, username: '', sender: '' },
  };
  useEffect(() => {
    if (kind === 'mcp') return;
    request<Record<string, unknown>>('/integrations/' + kind)
      .then((c) =>
        setText(JSON.stringify(Object.keys(c).length > 1 ? c : templates[kind], null, 2)),
      )
      .catch((e: unknown) => setStatus(String(e)));
    setSecret('');
  }, [kind]);
  if (kind === 'mcp')
    return (
      <>
        <button onClick={() => setKind('search')}>返回搜索与邮箱</button>
        <MCPServers request={request} act={act} sid={sid} onTask={onTask} />
      </>
    );
  return (
    <>
      <h2>连接外部服务</h2>
      <select value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="search">搜索 API</option>
        <option value="email">SMTP 邮箱（默认关闭）</option>
        <option value="mcp">MCP 服务</option>
      </select>
      <p>配置只定义连接方式，不授予发送、启动进程或调用工具权限。每次具体调用仍需任务授权。</p>
      <textarea
        style={{ width: '100%', height: 280 }}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {kind !== 'mcp' && (
        <label>
          密钥 / 应用密码（仅写入 Windows 凭据存储）
          <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} />
        </label>
      )}
      <button
        onClick={() =>
          act(async () => {
            await request('/integrations/' + kind, 'PUT', {
              ...JSON.parse(text),
              ...(secret ? { secret } : {}),
            });
            setSecret('');
            setStatus('已保存；实际调用仍需授权');
          })
        }
      >
        保存连接
      </button>

      <p className="notice">
        {status ||
          '密钥不要放入上方 JSON；搜索依赖实际服务账户。SMTP 仅支持加密 465 端口模式。远程 MCP OAuth 配置尚不支持。'}
      </p>
    </>
  );
}
