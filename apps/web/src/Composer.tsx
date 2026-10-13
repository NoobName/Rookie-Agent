import React from 'react';
import type { Task, Session, PlanResponse, Skill, Project } from '../../../packages/contracts';
import type { Workbench } from './useWorkbench';
import { request } from './api';
import { labels } from './workbenchDefaults';
import { ContextIndicator } from './ContextIndicator';
import { conversationStatus } from './ConversationTimeline';

export function Composer({
  boot,
  sid,
  tid,
  messages,
  input,
  busy,
  provider,
  spec,
  attachments,
  mode,
  collaboration,
  collaborator,
  task,
  locked,
  editable,
  steering,
  lastUsage,
  contextEstimate,
  limit,
  contextBudget,
  compaction,
  setTid,
  setInput,
  setAttachments,
  upload,
  controls,
  act,
  session,
  newTask,
}: Pick<
  Workbench,
  | 'boot'
  | 'sid'
  | 'tid'
  | 'messages'
  | 'input'
  | 'busy'
  | 'provider'
  | 'spec'
  | 'attachments'
  | 'mode'
  | 'collaboration'
  | 'collaborator'
  | 'task'
  | 'locked'
  | 'editable'
  | 'steering'
  | 'lastUsage'
  | 'contextEstimate'
  | 'limit'
  | 'contextBudget'
  | 'compaction'
  | 'setTid'
  | 'setInput'
  | 'setAttachments'
  | 'upload'
  | 'controls'
  | 'act'
  | 'session'
  | 'newTask'
>) {
  return (
    <div className="composer">
      <div className="context-strip" aria-label="上下文与执行状态">
        <ContextIndicator
          budget={contextBudget}
          usage={lastUsage}
          limit={limit}
          estimate={contextEstimate}
          input={input}
          compaction={compaction}
        />
        <span className={'execution-state ' + (locked ? 'executing' : '')}>
          {conversationStatus(
            boot.tasks.find((t: Task) => t.session_id === sid)?.state ||
              (messages.length ? 'completed' : undefined),
            busy,
          )}
        </span>
      </div>
      <textarea
        aria-label="消息"
        onPaste={(e) => {
          for (const file of Array.from(e.clipboardData.files)) act(() => upload(file));
        }}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="提出问题，或描述你希望完成的任务…"
      />
      <div>
        {attachments.map((a) => (
          <button
            key={a.id}
            onClick={() => setAttachments((xs) => xs.filter((x) => x.id !== a.id))}
          >
            {a.name} ×
          </button>
        ))}
      </div>
      <div className="row">
        <label className="upload">
          ＋ 附件
          <input
            type="file"
            onChange={(e) =>
              act(async () => {
                if (e.target.files?.[0]) {
                  await upload(e.target.files[0]);
                }
              })
            }
          />
        </label>
        <div>
          <button disabled={busy || !input} onClick={() => newTask()}>
            创建任务
          </button>{' '}
          <button
            disabled={busy || !input}
            onClick={() =>
              act(async () => {
                if (steering) {
                  await request(`/tasks/${tid}/feedback`, 'POST', {
                    content: input,
                    attachments: attachments.map((a) => a.id),
                  });
                  if (task?.spec.conversational) await request(`/tasks/${tid}/start`, 'POST', {});
                } else {
                  const s = await session();
                  const turn = await request<{ task_id?: string }>(`/sessions/${s}/chat`, 'POST', {
                    content: input,
                    provider,
                    execute: true,
                    mode,
                    collaboration,
                    collaboration_mapping: collaborator ? { reviewer: collaborator } : {},
                    attachments: attachments.map((a) => a.id),
                  });
                  if (turn.task_id) setTid(turn.task_id);
                }
                setInput('');
                setAttachments([]);
              })
            }
          >
            {steering ? '提交反馈' : '发送'} ↑
          </button>
        </div>
      </div>
      <div className="composer-toolbar">
        <select
          aria-label="当前模型"
          disabled={locked}
          value={provider}
          onChange={(e) => act(() => controls({ provider: e.target.value }))}
        >
          {boot.providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label="底部权限模式"
          title="帮我审批：工作区内读取、新建和修改文件自动批准；终端遵循已授予的权限"
          disabled={locked}
          value={mode}
          onChange={(e) => act(() => controls({ mode: e.target.value as 'ask' | 'workspace' }))}
        >
          <option value="ask">权限 · 都要申请</option>
          <option value="workspace">权限 · 帮我审批</option>
        </select>
        <select
          aria-label="协作模式"
          disabled={locked}
          value={collaboration ? 'multi' : 'single'}
          onChange={(e) => act(() => controls({ collaboration: e.target.value === 'multi' }))}
        >
          <option value="single">协作 · 单模型</option>
          <option value="multi">协作 · 多模型</option>
        </select>
        {collaboration && (
          <select
            aria-label="协作审阅模型"
            disabled={locked}
            value={collaborator}
            onChange={(e) =>
              act(() =>
                controls({
                  collaboration_mapping: e.target.value ? { reviewer: e.target.value } : {},
                }),
              )
            }
          >
            <option value="">选择审阅模型</option>
            {boot.providers
              .filter((p) => p.id !== 'scripted')
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        )}
      </div>
      <small>
        {locked
          ? '执行中需先暂停才能切换模型、权限或协作。'
          : editable
            ? '切换会更新当前计划，已有验收需重新执行。'
            : '直接发送可回答问题、处理附件或执行操作，沿用当前工作区与权限。'}
        {mode === 'workspace' ? ' 工作区内读取和写入自动批准；终端按已授予的权限执行。' : ''}
      </small>
    </div>
  );
}
