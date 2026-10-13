import React from 'react';
export function FailureReply({ event, calls }: any) {
  const detail = String(event.payload.detail || '执行记录未提供具体原因。');
  const related = detail.includes('验收或工具执行')
    ? calls.filter((c: any) => c.status === 'failed' && c.created <= event.created).slice(-3)
    : [];
  return (
    <div className="message assistant failure-reply" role="status" aria-label="执行中止原因">
      <small>Agent · 执行反馈</small>
      <p>本轮执行已停止，需要你处理。</p>
      <p>
        <strong>需要处理的问题：</strong>
        {detail}
      </p>
      {related.map((c: any) => (
        <p key={c.id}>
          {c.tool}：
          {c.result?.error ||
            `退出码 ${c.result?.exit_code ?? '未知'}，请展开本轮执行记录查看输出。`}
        </p>
      ))}
      {detail.includes('上下文保护阈值') && (
        <p>
          本轮模型回复与工具输出合计超过了上下文容量限制。可以缩小本次任务范围，或减少一次返回的文件、终端输出后继续。
        </p>
      )}
    </div>
  );
}
