import React, { useState } from 'react';
function inline(text: string): React.ReactNode[] {
  return text
    .split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g)
    .map((part, i) => {
      if (part.startsWith('`') && part.endsWith('`'))
        return <code key={i}>{part.slice(1, -1)}</code>;
      if (part.startsWith('**') && part.endsWith('**'))
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      if (link)
        return (
          <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer">
            {link[1]}
          </a>
        );
      return part;
    });
}
function Code({ code, language }: { code: string; language: string }) {
  const [status, setStatus] = useState('复制代码');
  return (
    <div className="code-block">
      <div className="row">
        <small>{language || '代码'}</small>
        <button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(code);
              setStatus('已复制');
            } catch {
              setStatus('复制失败，请手动选择');
            }
          }}
        >
          {status}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
export function MessageContent({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n'),
    out: React.ReactNode[] = [];
  for (let i = 0; i < lines.length; ) {
    const line = lines[i],
      fence = line.match(/^\s*```(.*)$/);
    if (fence) {
      let end = i + 1;
      while (end < lines.length && !/^\s*```\s*$/.test(lines[end])) end++;
      out.push(
        <Code key={i} language={fence[1].trim()} code={lines.slice(i + 1, end).join('\n')} />,
      );
      i = end + 1;
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      out.push(<h3 key={i}>{inline(heading[2])}</h3>);
      i++;
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      let end = i;
      const items = [];
      while (end < lines.length && (ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/).test(lines[end])) {
        items.push(<li key={end}>{inline(lines[end].replace(/^\s*([-*]|\d+\.)\s+/, ''))}</li>);
        end++;
      }
      out.push(ordered ? <ol key={i}>{items}</ol> : <ul key={i}>{items}</ul>);
      i = end;
      continue;
    }
    out.push(<p key={i}>{inline(line)}</p>);
    i++;
  }
  return <div className="rich-message">{out}</div>;
}
