import React, { useState, useEffect } from 'react';
export function ProjectDialog({ request, onCreated, onClose }: any) {
  const [name, setName] = useState(''),
    [workspace, setWorkspace] = useState(''),
    [listing, setListing] = useState<any>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  async function browse(path = '') {
    setError('');
    try {
      setListing(await request('/directories?path=' + encodeURIComponent(path)));
    } catch (e) {
      setError(String(e));
    }
  }
  async function choose() {
    if ((window as any).desktop) {
      const path = await (window as any).desktop.pickDirectory();
      if (path) setWorkspace(path);
    } else await browse(workspace);
  }
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        className="project-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose();
        }}
      >
        <div className="row">
          <h2 id="project-title">创建项目</h2>
          <button aria-label="关闭创建项目" onClick={onClose}>
            ×
          </button>
        </div>
        <label>
          项目名称
          <input
            autoFocus
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：我的 Agent 项目"
          />
        </label>
        <label>
          项目工作区
          <input
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            placeholder="选择文件夹，或输入本机绝对路径"
          />
        </label>
        <button
          className="folder-picker"
          onClick={() => choose().catch((e) => setError(String(e)))}
        >
          ▱ 选择本机文件夹
        </button>
        {listing && (
          <div className="directory-browser">
            <div className="row">
              <button onClick={() => browse(listing.parent)}>↑ 上一级</button>
              <button
                onClick={() => {
                  setWorkspace(listing.path);
                  setListing(null);
                }}
              >
                选择此文件夹
              </button>
            </div>
            <p className="path">{listing.path}</p>
            <div className="row">
              {listing.drives.map((d: string) => (
                <button key={d} onClick={() => browse(d)}>
                  {d}
                </button>
              ))}
            </div>
            <div className="directory-list">
              {listing.directories.map((d: any) => (
                <button key={d.path} onClick={() => browse(d.path)}>
                  ▱ {d.name}
                </button>
              ))}
            </div>
          </div>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button onClick={onClose}>取消</button>
          <button
            className="primary"
            disabled={busy || !name.trim() || !workspace.trim()}
            onClick={async () => {
              setBusy(true);
              setError('');
              try {
                const project = await request('/projects', 'POST', { name, workspace });
                await onCreated(project);
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            创建项目
          </button>
        </div>
      </section>
    </div>
  );
}

export function ConversationList({ sessions, sid, onSelect, onDelete }: any) {
  const [menu, setMenu] = useState('');
  useEffect(() => {
    if (!menu) return;
    const outside = (e: Event) => {
      if (
        !(e.target instanceof Element) ||
        e.target.closest('.session-row')?.getAttribute('data-session-id') !== menu
      )
        setMenu('');
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMenu('');
        document.getElementById('session-more-' + menu)?.focus();
      }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [menu]);
  return sessions.map((s: any) => (
    <div
      data-session-id={s.id}
      className={'session-row ' + (s.id === sid ? 'selected' : '')}
      key={s.id}
    >
      <button
        className="nav session-name"
        onClick={() => {
          setMenu('');
          onSelect(s);
        }}
      >
        ◌ {s.title}
      </button>
      <button
        id={'session-more-' + s.id}
        className="session-more"
        aria-label={'会话菜单：' + s.title}
        aria-haspopup="menu"
        aria-expanded={menu === s.id}
        onClick={() => setMenu(menu === s.id ? '' : s.id)}
      >
        ⋯
      </button>
      {menu === s.id && (
        <div className="session-menu" role="menu">
          <button
            role="menuitem"
            className="danger"
            onClick={() => {
              setMenu('');
              onDelete(s.id);
            }}
          >
            删除对话
          </button>
        </div>
      )}
    </div>
  ));
}
