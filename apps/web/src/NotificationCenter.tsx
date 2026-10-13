import React, { useEffect, useState } from 'react';
import { approvalSound } from './alerts';
const notificationTitle = (title: string) =>
  title?.includes('任务失败') ? '执行已停止，需要你处理' : title;
export function NotificationCenter({
  request,
  onTask,
}: {
  request: (path: string) => Promise<any>;
  onTask?: (id: string) => void;
}) {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => {
    let live = true,
      cursor = 0,
      ready = false,
      busy = false;
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const data = await request(
          '/notifications' + (ready ? '?after=' + cursor : '?latest=true'),
        );
        if (!live) return;
        cursor = data.cursor;
        ready = true;
        if (data.events.length) {
          setItems((xs) => [...xs, ...data.events].slice(-10));
          if (data.events.some((e: any) => e.payload.kind === 'approval')) approvalSound();
          if (
            !(window as any).desktop &&
            'Notification' in window &&
            Notification.permission === 'granted'
          )
            for (const e of data.events)
              new Notification('Rookie Agent', { body: notificationTitle(e.payload.title) });
        }
      } catch {
      } finally {
        busy = false;
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [request]);
  return items.length ? (
    <section aria-label="通知" className="banner notification-list">
      <b>通知</b>
      {items.map((e) => (
        <div key={e.id}>
          {notificationTitle(e.payload.title)}
          {e.payload.kind === 'approval' && onTask && (
            <button onClick={() => onTask(e.task_id || e.payload.task_id)}>查看授权</button>
          )}
          <button
            aria-label="关闭通知"
            onClick={() => setItems((xs) => xs.filter((x) => x.id !== e.id))}
          >
            关闭
          </button>
        </div>
      ))}
    </section>
  ) : null;
}
