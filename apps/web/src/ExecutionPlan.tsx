import React from 'react';

type PlanEvent = { type: string; payload: Record<string, unknown> };
type Step = { title: string; status: string };

export function ExecutionPlan({ events }: { events: PlanEvent[] }) {
  const plan = events.filter((event) => event.type === 'task_plan').at(-1)?.payload;
  if (!plan || !Array.isArray(plan.steps)) return null;
  const steps = plan.steps.filter(
    (step): step is Step =>
      !!step && typeof step.title === 'string' && typeof step.status === 'string',
  );
  const completed = steps.filter((step) => step.status === 'completed').length;
  return (
    <details className="execution-plan">
      <summary>
        执行步骤 · {completed}/{steps.length}
      </summary>
      <ol>
        {steps.map((step, index) => (
          <li key={index}>
            {step.status === 'completed' ? '✓' : step.status === 'in_progress' ? '◌' : '○'}{' '}
            {step.title}
          </li>
        ))}
      </ol>
      {typeof plan.summary === 'string' && plan.summary && <p>{plan.summary}</p>}
      {typeof plan.next_action === 'string' && plan.next_action && (
        <p>下一步：{plan.next_action}</p>
      )}
    </details>
  );
}
