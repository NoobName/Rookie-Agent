import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

test('回合额度用完可直接继续，保留计划且不重放写入', async ({ page, request }) => {
  const token = fs
    .readFileSync(path.join(process.env.AGENT_DATA || 'data', 'client.token'), 'utf8')
    .trim();
  const headers = { Authorization: 'Bearer ' + token };
  let tid = '';
  await page.route('**/api/sessions/*/chat', async (route) => {
    const sid = route.request().url().split('/').at(-2);
    const task = await (
      await request.post(`/api/sessions/${sid}/tasks`, {
        headers,
        data: {
          goal: '回合继续测试',
          workspace: '',
          mode: 'workspace',
          provider: 'scripted',
          deliverables: ['once.txt'],
          acceptance: ['检查文件'],
          tools: ['files.write'],
          guardrails: { max_steps: 1 },
          script: [{ name: 'files.write', arguments: { path: 'once.txt', content: 'ONE_WRITE' } }],
        },
      })
    ).json();
    tid = task.id;
    await request.post(`/api/tasks/${tid}/start`, { headers, data: {} });
    await route.fulfill({ json: { task_id: tid } });
  });
  await page.goto('/#token=' + token);
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByLabel('消息', { exact: true }).fill('回合继续测试');
  await page.getByRole('button', { name: '发送 ↑', exact: true }).click();
  await expect(page.getByLabel('需要用户操作的原因')).toContainText('不需要修改需求');
  await expect(page.locator('.composer .execution-state')).toContainText('可继续');
  await page.getByRole('button', { name: '继续下一轮', exact: true }).click();
  await expect(page.getByRole('button', { name: '接受结果', exact: true })).toBeVisible();
  const calls = await (await request.get(`/api/tasks/${tid}/calls`, { headers })).json();
  expect(calls.filter((call: { tool: string }) => call.tool === 'files.write')).toHaveLength(1);
});
