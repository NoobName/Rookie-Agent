import { useState, useEffect, useRef } from 'react';
import type {
  Task,
  TaskSpec,
  AgentEvent,
  Bootstrap,
  ChatMessage,
  ToolCall,
  Session,
} from '../../../packages/contracts';
import { API, token, request } from './api';
import { blank } from './workbenchDefaults';
let restored: Partial<{ sid: string; tid: string; input: string }> = {};
try {
  restored = JSON.parse(sessionStorage.getItem('ui-refresh-draft') || '{}');
  sessionStorage.removeItem('ui-refresh-draft');
} catch {}
export function useWorkbench() {
  const [boot, setBoot] = useState<Bootstrap>({
      sessions: [],
      tasks: [],
      providers: [],
      projects: [],
      tools: [],
    }),
    [sid, setSid] = useState(restored.sid || ''),
    [tid, setTid] = useState(restored.tid || ''),
    [messages, setMessages] = useState<ChatMessage[]>([]),
    [events, setEvents] = useState<AgentEvent[]>([]),
    [calls, setCalls] = useState<ToolCall[]>([]);
  const [input, setInput] = useState(restored.input || ''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [view, setView] = useState('chat'),
    [provider, setProvider] = useState('scripted'),
    [spec, setSpec] = useState<TaskSpec>(blank),
    [editing, setEditing] = useState(false),
    [auth, setAuth] = useState(token),
    [connected, setConnected] = useState(false);
  const [attachments, setAttachments] = useState<{ id: string; name: string }[]>([]),
    [questions, setQuestions] = useState<string[]>([]);
  async function upload(file: File) {
    const form = new FormData();
    form.append('file', file);
    const f = await request<{ id: string; name: string }>('/attachments', 'POST', form);
    setAttachments((a) => [...a, { id: f.id, name: f.name }]);
  }
  const [projectId, setProjectId] = useState(''),
    [projectDialog, setProjectDialog] = useState(false),
    [mode, setMode] = useState<'ask' | 'workspace'>('ask'),
    [collaboration, setCollaboration] = useState(false),
    [collaborator, setCollaborator] = useState('');
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const chatScroll = useRef<HTMLDivElement>(null),
    followBottom = useRef(true);
  useEffect(() => {
    followBottom.current = true;
  }, [sid]);
  useEffect(() => {
    if (followBottom.current && chatScroll.current)
      chatScroll.current.scrollTop = chatScroll.current.scrollHeight;
  }, [messages, events, calls]);
  const uiEpoch = useRef(0),
    working = useRef(false);
  const task: Task | undefined = boot.tasks.find((t: Task) => t.id === tid);

  const project = boot.projects?.find((p) => p.id === projectId);
  const locked =
    busy || (!!task && ['running', 'verifying', 'awaiting_approval'].includes(task.state));
  const editable =
    task &&
    !(task.spec.conversational && task.state === 'awaiting_feedback') &&
    ['planned', 'paused', 'failed', 'waiting_for_user', 'awaiting_feedback'].includes(task.state);
  useEffect(() => {
    const current = boot.sessions.find((s) => s.id === sid);
    if (current) setProjectId(current.project_id || '');
  }, [sid]);
  useEffect(() => {
    if (task) {
      setProvider(task.spec.provider);
      setMode(task.spec.mode);
      setCollaboration(task.spec.collaboration);
      setCollaborator((Object.values(task.spec.collaboration_mapping || {})[0] as string) || '');
    }
  }, [tid, task?.revision]);
  async function controls(patch: Partial<TaskSpec>) {
    if (editable) await request(`/tasks/${task.id}/spec`, 'PUT', { ...task.spec, ...patch });
    if (patch.provider !== undefined) setProvider(patch.provider);
    if (patch.mode !== undefined) setMode(patch.mode);
    if (patch.collaboration !== undefined) setCollaboration(patch.collaboration);
    if (patch.collaboration_mapping)
      setCollaborator(Object.values(patch.collaboration_mapping)[0] || '');
  }
  function selectSession(s: Session) {
    setSid(s.id);
    setProjectId(s.project_id || '');
    setTid(boot.tasks.find((t: Task) => t.session_id === s.id)?.id || '');
    setView('chat');
    setAttachments([]);
    setMessages([]);
  }
  function deleteSession(id: string) {
    if (window.confirm('删除此对话及关联任务记录？工作区文件将保留。'))
      act(async () => {
        await request('/sessions/' + id, 'DELETE');
        if (id === sid) {
          setSid('');
          setTid('');
          setMessages([]);
          setEvents([]);
          setCalls([]);
        }
        setView('chat');
      });
  }
  const steering =
    task &&
    (!task.spec.conversational
      ? [
          'planned',
          'running',
          'awaiting_approval',
          'verifying',
          'awaiting_feedback',
          'paused',
          'failed',
          'waiting_for_user',
        ]
      : ['planned', 'running', 'awaiting_approval', 'verifying', 'paused', 'waiting_for_user']
    ).includes(task.state);
  const lastUsage = (task ? [...events] : []).reverse().find((e) => e.type === 'usage');
  const contextEstimate = Math.ceil(
    (messages.slice(-20).reduce((n, m) => n + m.content.length, 0) +
      (task ? JSON.stringify(task.spec).length + JSON.stringify(calls.slice(-10)).length : 0) +
      input.length) /
      3,
  );
  const limit = Number(boot.providers.find((p) => p.id === provider)?.profile?.context_window) || 0;
  const contextBudget = (task ? [...events] : [])
    .reverse()
    .find((e) => e.type === 'context_budget')?.payload;
  const compaction = (task ? [...events] : [])
    .reverse()
    .find((e) => e.type === 'context_compacted')?.payload;

  async function load() {
    const b = await request<Bootstrap>('/bootstrap');
    if (tid && b.tasks.some((t: Task) => t.id === tid))
      setCalls(await request<ToolCall[]>(`/tasks/${tid}/calls`));
    else setCalls([]);
    setBoot(b);
    setConnected(true);
    if (sid && !b.sessions.some((s) => s.id === sid)) setSid('');
    if (!b.providers.some((p) => p.id === provider)) setProvider('scripted');
    return b;
  }
  async function act(fn: () => Promise<unknown>) {
    while (working.current) await new Promise((resolve) => setTimeout(resolve, 20));
    working.current = true;
    uiEpoch.current++;
    setCalls((xs) => xs.filter((c) => c.status !== 'pending'));
    setError('');
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(String(e));
      await load().catch(() => {});
    } finally {
      working.current = false;
      uiEpoch.current++;
      setBusy(false);
    }
  }
  useEffect(() => {
    load().catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    let live = true;
    if (sid)
      request<ChatMessage[]>('/sessions/' + sid + '/messages')
        .then((rows) => {
          if (live) setMessages(rows);
        })
        .catch((e) => {
          if (live) setError(String(e));
        });
    else setMessages([]);
    return () => {
      live = false;
    };
  }, [sid, boot]);
  useEffect(() => {
    if (!tid) {
      setEvents([]);
      setCalls([]);
      return;
    }
    let live = true;
    let cursor = 0;
    let fetching = false;
    setEvents([]);
    setCalls([]);
    const poll = async () => {
      if (fetching || working.current) return;
      const epoch = uiEpoch.current;
      fetching = true;
      try {
        const [e, c, b] = await Promise.all([
          request<AgentEvent[]>(`/tasks/${tid}/events?after=${cursor}`),
          request<ToolCall[]>(`/tasks/${tid}/calls`),
          request<Bootstrap>('/bootstrap'),
        ]);
        if (live && epoch === uiEpoch.current && !working.current) {
          if (e.length) cursor = e[e.length - 1].id;
          setEvents((prev) => [...prev, ...e].slice(-2000));
          setCalls(c);
          setBoot(b);
        }
      } catch (e) {
        if (live) setError(String(e));
      } finally {
        fetching = false;
      }
    };
    poll();
    const id = setInterval(poll, 900);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [tid]);
  async function session() {
    if (sid) return sid;
    const s = await request<Session>('/sessions', 'POST', {
      title: input.slice(0, 35) || '新会话',
      project_id: projectId || null,
    });
    setSid(s.id);
    return s.id;
  }
  function newTask(demo = false) {
    setEditing(false);
    setSpec({
      ...blank,
      provider,
      workspace: project?.workspace || '',
      mode,
      collaboration,
      collaboration_mapping: collaborator ? { reviewer: collaborator } : {},
      inputs: attachments.map((a) => a.id),
      goal: demo ? '演示：创建 Python 问候函数并运行断言测试' : input,
      deliverables: demo ? ['hello_agent.py'] : [],
      acceptance: demo ? ['Python 断言测试退出码为 0'] : [],
    });
    setView('plan');
  }
  async function savePlan() {
    const s = await session();
    const payload = {
      ...spec,
      deliverables: spec.deliverables.map((x) => x.trim()).filter(Boolean),
      acceptance: spec.acceptance.map((x) => x.trim()).filter(Boolean),
    };
    const t = editing
      ? await request<Task>(`/tasks/${tid}/spec`, 'PUT', payload)
      : await request<Task>(`/sessions/${s}/tasks`, 'POST', payload);
    setTid(t.id);
    setView('chat');
    setAttachments([]);
  }
  async function download(path: string) {
    const r = await fetch(`${API}/api/tasks/${tid}/artifact?path=${encodeURIComponent(path)}`, {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (!r.ok) throw new Error('下载失败');
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = path.split(/[\\/]/).pop()!;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return {
    boot,
    sid,
    tid,
    messages,
    events,
    calls,
    input,
    error,
    busy,
    view,
    provider,
    spec,
    editing,
    auth,
    connected,
    attachments,
    questions,
    projectId,
    projectDialog,
    mode,
    collaboration,
    collaborator,
    inspectorOpen,
    chatScroll,
    followBottom,
    task,
    project,
    locked,
    editable,
    steering,
    lastUsage,
    contextEstimate,
    limit,
    contextBudget,
    compaction,
    setSid,
    setTid,
    setMessages,
    setEvents,
    setCalls,
    setInput,
    setError,
    setView,
    setProvider,
    setSpec,
    setEditing,
    setAuth,
    setAttachments,
    setQuestions,
    setProjectId,
    setProjectDialog,
    setMode,
    setCollaboration,
    setCollaborator,
    setInspectorOpen,
    upload,
    controls,
    selectSession,
    deleteSession,
    load,
    act,
    session,
    newTask,
    savePlan,
    download,
  };
}
export type Workbench = ReturnType<typeof useWorkbench>;
