import React from 'react';
export function ContextIndicator({ budget, usage, limit, estimate, input, compaction }: any) {
  const used =
    !input && budget ? budget.input_tokens : !input && usage ? usage.payload.input : estimate;
  const total = budget?.window || limit || 0;
  const percent = total ? Math.round((used / total) * 100) : null;
  return (
    <details className="context-indicator">
      <summary aria-label="上下文占用">
        ⌁ 上下文 · {percent === null ? '上限未配置' : `约 ${percent}% 已用`}
        {compaction ? ' · 已压缩' : ''}
      </summary>
      <div className="context-popover" role="note">
        <b>背景信息窗口</b>
        <p>{percent === null ? '真实模型上限尚未配置' : `约 ${percent}% 已用`}</p>
        <p>
          已用 {Number(used).toLocaleString()} token
          {total ? `，共 ${total.toLocaleString()} token` : ''}（
          {input
            ? '草稿估算'
            : budget
              ? '请求估算'
              : usage?.payload.estimated === false
                ? 'API 记录'
                : '估算'}
          ）
        </p>
        {budget && (
          <p>
            输入预算 {budget.input_limit.toLocaleString()} / 输出预留{' '}
            {budget.output_reserve.toLocaleString()}
            {budget.source === 'local_fallback' ? '（本地保守预算，不是模型容量）' : ''}
          </p>
        )}
        {total > 0 && (
          <progress aria-label="上下文占用比例" value={Math.min(used, total)} max={total} />
        )}
        <p>占用是本次输入，不是累计消耗；估算可能与模型分词有差异。</p>
        {compaction && <p>已自动压缩；后续请求复用压缩结果，接近阈值再压缩。完整日志保留。</p>}
      </div>
    </details>
  );
}
