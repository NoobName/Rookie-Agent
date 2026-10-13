import React from 'react';
import type { Task, Session, PlanResponse, Skill, Project } from '../../../packages/contracts';
import type { Workbench } from './useWorkbench';
import { request } from './api';
import { labels } from './workbenchDefaults';
import { ConversationList } from './Projects';
import { ThemeToggle } from './ThemeToggle';
import { InterfaceVersion } from './InterfaceVersion';

export function Sidebar({
  boot,
  sid,
  tid,
  input,
  spec,
  projectId,
  project,
  setSid,
  setTid,
  setMessages,
  setEvents,
  setView,
  setAttachments,
  setProjectId,
  setProjectDialog,
  selectSession,
  deleteSession,
  act,
}: Pick<
  Workbench,
  | 'boot'
  | 'sid'
  | 'tid'
  | 'input'
  | 'spec'
  | 'projectId'
  | 'project'
  | 'setSid'
  | 'setTid'
  | 'setMessages'
  | 'setEvents'
  | 'setView'
  | 'setAttachments'
  | 'setProjectId'
  | 'setProjectDialog'
  | 'selectSession'
  | 'deleteSession'
  | 'act'
>) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="mark">R</span>
        <div>
          Rookie Agent<small>你的个人工作台</small>
        </div>
      </div>
      <button
        className="new"
        onClick={() =>
          act(async () => {
            const s = await request<Session>('/sessions', 'POST', {
              title: '新会话',
              project_id: projectId || null,
            });
            setSid(s.id);
            setTid('');
            setMessages([]);
            setEvents([]);
            setView('chat');
          })
        }
      >
        ＋ 新建会话
      </button>
      <div className="project-heading">
        <span>项目</span>
        <button aria-label="新建项目" onClick={() => setProjectDialog(true)}>
          ＋
        </button>
      </div>
      {boot.projects?.map((p) => (
        <div key={p.id}>
          <button
            className={'nav project-nav ' + (projectId === p.id ? 'selected' : '')}
            title={p.workspace}
            onClick={() => {
              setProjectId(p.id);
              setSid('');
              setTid('');
              setMessages([]);
              setView('chat');
            }}
          >
            ▱ {p.name}
          </button>
          <div className="project-sessions">
            <ConversationList
              sessions={boot.sessions.filter((s) => s.project_id === p.id)}
              sid={sid}
              onSelect={selectSession}
              onDelete={deleteSession}
            />
          </div>
        </div>
      ))}
      <button
        className="section-label section-reset"
        onClick={() => {
          setProjectId('');
          setSid('');
          setTid('');
          setMessages([]);
          setView('chat');
        }}
      >
        对话
      </button>
      <ConversationList
        sessions={boot.sessions.filter((s) => !s.project_id)}
        sid={sid}
        onSelect={selectSession}
        onDelete={deleteSession}
      />
      <div className="section-label">任务历史</div>
      {boot.tasks
        .filter((t: Task) => t.session_id === sid)
        .map((t: Task) => (
          <button
            key={t.id}
            className={'nav ' + (tid === t.id ? 'selected' : '')}
            onClick={() => {
              setTid(t.id);
              setView('chat');
              setAttachments([]);
            }}
          >
            <span>{t.spec.goal}</span>
            <small>{labels[t.state]}</small>
          </button>
        ))}
      <div className="sidebar-bottom">
        <ThemeToggle />
        <InterfaceVersion
          refresh={() => {
            sessionStorage.setItem('ui-refresh-draft', JSON.stringify({ sid, tid, input }));
            location.reload();
          }}
        />
        <button className="nav" onClick={() => setView('settings')}>
          ⚙ 模型与设置
        </button>
        <button className="nav" onClick={() => setView('memory')}>
          ◇ 长期记忆
        </button>
        <button className="nav" onClick={() => setView('advanced')}>
          ⊞ 扩展与自动化
        </button>
        <span className="online">● 本地服务已连接</span>
      </div>
    </aside>
  );
}
