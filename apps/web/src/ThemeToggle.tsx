import React, { useState } from 'react';
const key = 'rookie-agent-theme';
let initial = 'light';
try {
  if (localStorage.getItem(key) === 'dark') initial = 'dark';
} catch {}
document.documentElement.dataset.theme = initial;
export function ThemeToggle() {
  const [theme, setTheme] = useState(initial);
  return (
    <button
      className="nav theme-toggle"
      aria-label="深色模式"
      aria-pressed={theme === 'dark'}
      onClick={() => {
        const next = theme === 'dark' ? 'light' : 'dark';
        setTheme(next);
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem(key, next);
        } catch {}
      }}
    >
      {theme === 'dark' ? '☀ 切换浅色模式' : '☾ 切换深色模式'}
    </button>
  );
}
