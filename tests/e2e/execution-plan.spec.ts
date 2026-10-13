import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

test('执行计划持续更新且默认折叠', async ({ page, request }) => {
  const data = process.env.AGENT_DATA || path.resolve('data');
  const token = fs.readFileSync(path.join(data, 'client.token'), 'utf8').trim();
  const headers = { Authorization: 'Bearer ' + token };
  await page.route('**/api/sessions/*/chat', async (route) => {
    const sid = route.request().url().split('/').at(-2);
    const response = await request.post(`/api/sessions/${sid}/tasks`, {
      headers,
      data: {
        conversational: true,
        goal: '维护执行步骤',
        deliverables: ['执行步骤'],
        acceptance: ['显示并保存步骤进展'],
        workspace: '',
        mode: 'workspace',
        tools: ['task.plan'],
        script: [
          {
            name: 'task.plan',
            arguments: {
              steps: [{ title: '检查代码', status: 'in_progress' }],
              next_action: '定位入口',
            },
          },
          {
            name: 'task.plan',
            arguments: {
              steps: [{ title: '检查代码', status: 'completed' }],
              summary: '代码检查结束',
            },
          },
        ],
      },
    });
    expect(response.ok()).toBeTruthy();
    const task = await response.json();
    await page.route(`**/api/tasks/${task.id}/events*`, async (eventRoute) => {
      const response = await eventRoute.fetch();
      const events = await response.json();
      await eventRoute.fulfill({
        json: [
          ...events,
          {
            id: 90001,
            task_id: task.id,
            created: task.created + 0.01,
            type: 'subagent_started',
            payload: { id: 'child-ui', objective: '检索光照实现' },
          },
          {
            id: 90002,
            task_id: task.id,
            created: task.created + 0.02,
            type: 'subagent_finished',
            payload: {
              id: 'child-ui',
              status: 'succeeded',
              output: '光照入口位于 render.py:20',
              tool_calls: 20,
            },
          },
        ],
      });
    });
    await request.post(`/api/tasks/${task.id}/start`, { headers, data: {} });
    await route.fulfill({ json: { task_id: task.id } });
  });
  await page.goto('/#token=' + token);
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByLabel('消息', { exact: true }).fill('维护执行步骤');
  await page.getByRole('button', { name: '发送 ↑', exact: true }).click();
  const plan = page.locator('.execution-plan');
  await expect(plan.locator('summary')).toHaveText('执行步骤 · 1/1');
  await expect(plan).not.toHaveAttribute('open', '');
  await expect(page.locator('.subagent-progress')).not.toHaveAttribute('open', '');
  await page.locator('.subagent-progress summary').click();
  await expect(page.locator('.subagent-progress')).toContainText('光照入口位于 render.py:20');
  await plan.locator('summary').click();
  await expect(plan).toContainText('代码检查结束');
  await page.reload();
  await page.getByRole('button', { name: '◌ 新会话', exact: true }).first().click();
  await expect(page.locator('.execution-plan summary')).toHaveText('执行步骤 · 1/1');
  await expect(page.locator('.execution-plan')).not.toHaveAttribute('open', '');
});
