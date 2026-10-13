import React from 'react';
export function ActionRequired({ task, events }: any) {
  if (!['waiting_for_user', 'paused', 'awaiting_approval', 'clarifying'].includes(task.state))
    return null;
  const event = [...events]
    .reverse()
    .find((e) => e.type === 'state' && e.payload.state === task.state);
  const reason =
    task.state_detail ||
    event?.payload.detail ||
    (
      {
        paused: '任务已暂停。',
        awaiting_approval: '有工具操作等待你的授权。',
        clarifying: '需要补充任务要求。',
      } as any
    )[task.state] ||
    '执行已停止，记录中没有具体原因。请展开执行记录查看最后一次操作。';
  const stopReason = task.stop_reason || event?.payload.reason;
  const next =
    stopReason === 'step_limit'
      ? '这只是本轮回合额度用完。点击“继续下一轮”即可沿用计划和已有进度，不需要修改需求。'
      : stopReason === 'no_progress'
        ? '模型在收到策略提醒后仍持续重复。请补充新的排查方向，或通过编辑计划调整方案后继续。'
        : task.state === 'awaiting_approval'
          ? '请查看授权卡片中的工具和参数，选择批准或拒绝。'
          : reason.includes('相同操作') || reason.includes('工具错误累计')
            ? '请查看最后重复的工具结果，在输入框补充修正方向后提交反馈；也可以通过“编辑计划 / 继续”审查后重试。'
            : reason.includes('预算')
              ? '请在“编辑计划 / 继续”中调整任务预算；如果是累计预算，请到扩展设置调整。保存后继续。'
              : reason.includes('步数')
                ? '本轮已达到执行步数上限。请审查已有成果，通过“编辑计划 / 继续”保存计划后开始下一轮，或补充下一步要求。'
                : '请在输入框补充要求并提交反馈，或通过“编辑计划 / 继续”审查并保存计划后继续。';
  return (
    <div className="message action-required" role="status" aria-label="需要用户操作的原因">
      <small>
        Agent ·{' '}
        {stopReason === 'step_limit'
          ? '本轮额度已用完，可继续'
          : stopReason === 'no_progress'
            ? '需要调整策略'
            : '需要你处理'}
      </small>
      <p>{reason}</p>
      <p>{next}</p>
    </div>
  );
}
