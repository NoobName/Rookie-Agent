import React, { useEffect, useState } from 'react';
export function InterfaceVersion({ refresh }: { refresh: () => void }) {
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    const current = Array.from(document.scripts)
      .find((s) => s.type === 'module')
      ?.getAttribute('src');
    let live = true;
    async function check() {
      try {
        const response = await fetch('/?ui-check=' + Date.now(), { cache: 'no-store' });
        if (!response.ok) return;
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        const next = doc.querySelector('script[type="module"]')?.getAttribute('src');
        if (live && current && next && current !== next) setChanged(true);
      } catch {}
    }
    const timer = setInterval(check, 30000);
    window.addEventListener('focus', check);
    return () => {
      live = false;
      clearInterval(timer);
      window.removeEventListener('focus', check);
    };
  }, []);
  return (
    <div className="interface-version">
      <small>界面 0.7.2</small>
      {changed && <button onClick={refresh}>发现新版界面 · 保留草稿并刷新</button>}
    </div>
  );
}
