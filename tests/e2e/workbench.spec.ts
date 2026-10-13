import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const data = process.env.AGENT_DATA || path.resolve('data');
const token = () => fs.readFileSync(path.join(data, 'client.token'), 'utf8').trim();

test('直接发送沿用权限并显示真实执行、授权和文件产物', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  let submitted: any;
  await page.route('**/api/sessions/*/chat', async (route) => {
    submitted = route.request().postDataJSON();
    const sid = route.request().url().split('/').at(-2);
    const task = await (
      await request.post(`/api/sessions/${sid}/tasks`, {
        headers,
        data: {
          conversational: true,
          goal: submitted.content,
          workspace: '',
          mode: submitted.mode,
          deliverables: ['chat-ui.txt'],
          acceptance: ['验证内容'],
          tools: ['files.write', 'terminal.run'],
          script: [
            { name: 'files.write', arguments: { path: 'chat-ui.txt', content: 'CHAT_UI_PROOF' } },
            {
              name: 'terminal.run',
              arguments: {
                argv: [
                  process.env.AGENT_PYTHON || 'python',
                  '-c',
                  "from pathlib import Path;assert Path('chat-ui.txt').read_text()=='CHAT_UI_PROOF';print('CHAT_UI_OK')",
                ],
              },
            },
          ],
        },
      })
    ).json();
    await request.post(`/api/tasks/${task.id}/start`, { headers, data: {} });
    await route.fulfill({ json: { task_id: task.id } });
  });
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByLabel('底部权限模式').selectOption('workspace');
  await page.getByLabel('消息', { exact: true }).fill('直接创建并验证文件');
  await page.getByRole('button', { name: '发送 ↑', exact: true }).click();
  expect(submitted.execute).toBe(true);
  expect(submitted.mode).toBe('workspace');
  await page.getByRole('button', { name: '批准这次操作' }).waitFor();
  await expect(page.locator('.approval')).toContainText('terminal.run');
  await expect(page.locator('.approval-banner')).toContainText('执行已暂停');
  await expect(page.getByLabel('执行过程')).toContainText('等待你的授权');
  await expect(page.locator('.execution-progress details')).not.toHaveAttribute('open', '');
  await page.locator('.execution-progress summary').click();
  await expect(page.locator('.progress-body')).toBeVisible();
  await page.locator('.execution-progress summary').click();
  await expect(page.getByRole('button', { name: '允许此工作区使用终端，不再询问' })).toBeVisible();
  await expect(page.getByLabel('底部权限模式')).toBeDisabled();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await page.locator('.turn-records>summary').click();
  await expect(page.getByRole('region', { name: '任务成果' })).toContainText('chat-ui.txt');
  await page
    .locator('.turn-records details.result>summary')
    .filter({ hasText: 'terminal.run' })
    .click();
  await expect(page.locator('.result pre').filter({ hasText: 'CHAT_UI_OK' })).toBeVisible();
  await expect(page.getByRole('button', { name: '发送 ↑', exact: true })).toBeVisible();
});

test('会话菜单不遮挡窗口，深色模式可持久切换', async ({ page }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  const more = page.locator('.session-row.selected .session-more');
  const point = await page.getByLabel('消息', { exact: true }).evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  const background = await page
    .locator('.composer')
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  await more.click();
  await expect(page.getByRole('menuitem', { name: '删除对话' })).toBeVisible();
  await page.mouse.move(point.x, point.y);
  expect(
    await page.evaluate(
      (p) => document.elementFromPoint(p.x, p.y)?.getAttribute('aria-label'),
      point,
    ),
  ).toBe('消息');
  expect(
    await page.locator('.composer').evaluate((el) => getComputedStyle(el).backgroundColor),
  ).toBe(background);
  await page.screenshot({ path: 'test-results/menu-light.png' });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
  await expect(more).toBeFocused();
  await more.click();
  await page.getByLabel('消息', { exact: true }).click();
  await expect(page.getByRole('menu')).toHaveCount(0);
  await page.getByRole('button', { name: '深色模式', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(
    await page.locator('.composer').evaluate((el) => getComputedStyle(el).backgroundColor),
  ).not.toBe(background);
  await more.click();
  await page.mouse.move(point.x, point.y);
  expect(
    await page.evaluate(
      (p) => document.elementFromPoint(p.x, p.y)?.getAttribute('aria-label'),
      point,
    ),
  ).toBe('消息');
  await page.screenshot({ path: 'test-results/menu-dark.png' });
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  await page.screenshot({ path: 'test-results/project-dark.png' });
  await page.getByRole('button', { name: '关闭创建项目' }).click();
  await page.getByRole('button', { name: '⚙ 模型与设置' }).click();
  await page.screenshot({ path: 'test-results/settings-dark.png' });
  await page.getByRole('button', { name: '深色模式', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('Rookie 项目、工作区、二级菜单及底部控制', async ({ page, request }) => {
  const workspace = path.join(data, 'project-ui');
  fs.mkdirSync(workspace, { recursive: true });
  await page.goto('/#token=' + token());
  await expect(page.locator('.brand')).toContainText('Rookie Agent');
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  await page.getByLabel('项目名称', { exact: true }).fill('Rookie UI 项目');
  await page.getByLabel('项目工作区', { exact: true }).fill(workspace);
  await page.getByRole('button', { name: '选择本机文件夹', exact: false }).click();
  await expect(page.locator('.directory-browser')).toContainText(workspace);
  await page.getByRole('button', { name: '选择此文件夹' }).click();
  await page.getByRole('button', { name: '创建项目', exact: true }).click();
  await expect(page.locator('header')).toContainText('Rookie UI 项目');
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await expect(page.locator('.project-sessions .session-row.selected')).toBeVisible();
  await expect(page.getByRole('menuitem', { name: '删除对话' })).toHaveCount(0);
  await page.getByLabel('底部权限模式').selectOption('workspace');
  await page.getByLabel('协作模式', { exact: true }).selectOption('multi');
  await expect(page.getByLabel('协作审阅模型')).toBeVisible();
  await page.getByLabel('协作模式', { exact: true }).selectOption('single');
  await page.getByLabel('消息').fill('项目测试任务');
  await expect(page.getByLabel('上下文占用', { exact: true })).toContainText('上下文');
  await page.getByRole('button', { name: '创建任务', exact: true }).click();
  await expect(page.getByLabel('工作区目录')).toHaveValue(workspace);
  await expect(page.getByLabel('权限模式', { exact: true })).toHaveValue('workspace');
  await page.getByLabel('交付物（每行一项）').fill('result.txt');
  await page.getByLabel('验收条件（每行一项）').fill('检查文件');
  await page.getByRole('button', { name: '保存计划', exact: true }).click();
  await page.getByLabel('底部权限模式').selectOption('ask');
  const headers = { Authorization: 'Bearer ' + token() };
  await expect
    .poll(async () => {
      const b = await (await request.get('/api/bootstrap', { headers })).json();
      return b.tasks.find((t: any) => t.spec.goal === '项目测试任务')?.spec.mode;
    })
    .toBe('ask');
  await expect(page.getByLabel('上下文与执行状态')).toContainText('需要用户操作');
  await page.screenshot({ path: 'test-results/rookie-projects.png', fullPage: true });
  await page.reload();
  await expect(page.locator('.project-nav')).toContainText('Rookie UI 项目');
  await page.locator('.project-sessions .session-more').click();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('menuitem', { name: '删除对话' }).click();
  await expect(page.locator('.project-sessions .session-row')).toHaveCount(0);
  expect(fs.existsSync(workspace)).toBeTruthy();
});

test('独立提醒无需选择任务也会显示通知', async ({ page, request }) => {
  await page.goto('/#token=' + token());
  await expect(page.getByRole('button', { name: '＋ 新建会话' })).toBeVisible();
  await page.waitForTimeout(2200);
  const now = Date.now() / 1000,
    title = '全局提醒 ' + Date.now();
  const response = await request.put('/api/schedules/new', {
    headers: { Authorization: 'Bearer ' + token() },
    data: {
      name: title,
      kind: 'reminder',
      next_run: now + 1,
      authorized_until: now + 60,
      timezone: 'Asia/Shanghai',
      missed: 'once',
    },
  });
  expect(response.ok()).toBeTruthy();
  await expect(page.getByRole('region', { name: '通知' })).toContainText(title, { timeout: 10000 });
  await page.getByRole('button', { name: '关闭通知' }).click();
  await expect(page.getByRole('region', { name: '通知' })).toHaveCount(0);
});

test('扩展设置：预算、评测、多个 MCP 与提醒表单', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() },
    pid = 'eval_' + Date.now();
  await request.put('/api/providers/' + pid, {
    headers,
    data: { id: pid, name: '评测样本', model: 'fixture', tools: true },
  });
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '⚙ 模型与设置' }).click();
  await page.getByLabel('累计 token 提醒', { exact: true }).fill('1000000');
  await page.getByRole('button', { name: '保存累计预算' }).click();
  expect((await (await request.get('/api/usage', { headers })).json()).limits.token_reminder).toBe(
    1000000,
  );
  await page.getByRole('combobox', { name: '评测模型', exact: true }).selectOption(pid);
  await page.getByRole('button', { name: '创建代码功能评测' }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('计划就绪');
  await expect(page.getByRole('button', { name: '开始执行', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '⊞ 扩展与自动化' }).click();
  await page.getByRole('button', { name: '定时任务', exact: true }).click();
  await page.getByLabel('名称 / 提醒内容').fill('UI synthetic reminder');
  await page.getByRole('button', { name: '保存并授权调度' }).click();
  await expect(page.locator('.result').filter({ hasText: 'UI synthetic reminder' })).toBeVisible();
  await page.getByRole('button', { name: '服务连接', exact: true }).click();
  await page.locator('.content select').selectOption('mcp');
  await page.getByLabel('服务配置 JSON').fill(
    JSON.stringify({
      id: 'ui_mcp_' + Date.now(),
      name: 'UI MCP',
      enabled: false,
      transport: 'stdio',
      command: 'python',
      args: ['examples/mcp_server.py'],
      url: '',
    }),
  );
  await page.getByRole('button', { name: '保存 MCP 服务', exact: true }).click();
  await expect(page.getByRole('button', { name: 'UI MCP（停用）', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/mcp-settings.png', fullPage: true });
});

test('任务成果：安全预览、累计用量、导出摘要', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (await request.post('/api/sessions', { headers, data: { title: '成果预览测试' } })).json()
  ).id;
  const task = await (
    await request.post(`/api/sessions/${sid}/tasks`, {
      headers,
      data: {
        goal: '安全产物预览',
        workspace: '',
        deliverables: ['proof.html'],
        acceptance: ['人工查看'],
        mode: 'workspace',
        provider: 'scripted',
        tools: ['files.write'],
        script: [
          {
            name: 'files.write',
            arguments: {
              path: 'proof.html',
              content: '<script>window.previewInjected=true</script>\npreview proof',
            },
          },
        ],
      },
    })
  ).json();
  await request.post(`/api/tasks/${task.id}/start`, { headers, data: {} });
  await expect
    .poll(async () => {
      const b = await (await request.get('/api/bootstrap', { headers })).json();
      return b.tasks.find((t: any) => t.id === task.id).state;
    })
    .toBe('awaiting_feedback');
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 成果预览测试', exact: true }).click();
  await page.getByRole('button', { name: /安全产物预览/ }).click();
  await page.locator('.turn-records>summary').click();
  const results = page.getByRole('region', { name: '任务成果' });
  await expect(results).toContainText('累计 2 次已记录响应');
  await results.getByRole('button', { name: '预览', exact: true }).click();
  await expect(results.locator('.artifact-preview pre')).toContainText(
    '<script>window.previewInjected=true</script>',
  );
  expect(await page.evaluate(() => (window as any).previewInjected)).toBeUndefined();
  const download = page.waitForEvent('download');
  await results.getByRole('button', { name: '导出执行摘要' }).click();
  const report = await download;
  const file = await report.path();
  const value = JSON.parse(fs.readFileSync(file!, 'utf8'));
  expect(value.task_id).toBe(task.id);
  expect(value.state).toBe('awaiting_feedback');
  expect(value.artifacts[0].path).toBe('proof.html');
  await page.screenshot({ path: 'test-results/task-results.png', fullPage: true });
});

test('安全富文本：代码块、复制、HTML 和危险链接不执行', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.route('**/api/sessions/*/chat', (route) =>
    route.fulfill({
      json: {
        content:
          '**说明**\n```python\nassert 1 + 1 == 2\n```\n<script>window.agentInjected=true</script>\n[危险](javascript:alert(1))\n[来源](https://example.com)',
      },
    }),
  );
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  // Use persisted messages: the application reloads history after chat requests.
  const headers = { Authorization: 'Bearer ' + token() };
  const response = await page.request.get('/api/bootstrap', { headers });
  const sid = (await response.json()).sessions[0].id;
  await page.route(`**/api/sessions/${sid}/messages`, (route) =>
    route.fulfill({
      json: [
        {
          id: 'fixture',
          role: 'assistant',
          content:
            '**说明**\n```python\nassert 1 + 1 == 2\n```\n<script>window.agentInjected=true</script>\n[危险](javascript:alert(1))\n[来源](https://example.com)',
        },
      ],
    }),
  );
  await page.getByLabel('消息').fill('展示格式');
  await page.getByRole('button', { name: '发送 ↑' }).click();
  await expect(page.locator('.message pre code')).toHaveText('assert 1 + 1 == 2');
  await page.getByRole('button', { name: '复制代码', exact: true }).click();
  await expect(page.getByRole('button', { name: '已复制', exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('assert 1 + 1 == 2');
  await expect(page.locator('.message script')).toHaveCount(0);
  await expect(page.locator('.message a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).agentInjected)).toBeUndefined();
  await expect(page.getByRole('link', { name: '来源' })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  );
  await page.screenshot({ path: 'test-results/rich-text.png', fullPage: true });
});

test('记忆版本、导出和技能应用只生成待审查计划', async ({ page, request }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByRole('button', { name: '◇ 长期记忆' }).click();
  await page.getByLabel('记忆内容').fill('旧版决定 alpha');
  await page.getByRole('button', { name: '保存记忆' }).click();
  const item = page.locator('.result').filter({ hasText: '旧版决定 alpha' });
  await item.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('记忆内容').fill('新版决定 beta');
  await page.getByRole('button', { name: '保存记忆' }).click();
  const updated = page.locator('.result').filter({ hasText: '新版决定 beta' });
  await updated.getByRole('button', { name: '版本历史' }).click();
  await expect(page.getByRole('heading', { name: '编辑前的历史版本' })).toBeVisible();
  await expect(page.locator('pre').filter({ hasText: '旧版决定 alpha' })).toBeVisible();
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出全部记忆' }).click();
  expect((await dl).suggestedFilename()).toBe('agent-memories.json');
  await updated.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.locator('pre').filter({ hasText: '旧版决定 alpha' })).toHaveCount(0);
  await page.getByRole('button', { name: '⊞ 扩展与自动化' }).click();
  await page.getByRole('button', { name: '项目检查', exact: true }).click();
  const headers = { Authorization: 'Bearer ' + token() },
    before = (await (await request.get('/api/bootstrap', { headers })).json()).tasks.length;
  await page.getByRole('button', { name: '使用此技能创建计划' }).click();
  await expect(page.getByRole('heading', { name: '把需求变成可执行计划' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: '执行计划', exact: true })).toHaveValue(
    /files.list/,
  );
  await expect(page.getByRole('textbox', { name: '上下文与补充说明', exact: true })).toHaveValue(
    /source_id/,
  );
  const after = await (await request.get('/api/bootstrap', { headers })).json();
  expect(after.tasks.length).toBe(before);
});

test('设置修复：空模型拦截、密钥状态、错误提示、删除模型和会话', async ({ page }) => {
  const id = 'ui_settings_' + Date.now();
  let stored = false;
  await page.route(`**/api/providers/${id}/credential`, async (route) => {
    if (route.request().method() === 'POST') {
      stored = true;
      await route.fulfill({ json: { ok: true } });
    } else
      await route.fulfill({
        json: {
          saved: stored,
          detail: stored
            ? '密钥已保存，输入框留空表示保留；不会回显密钥。'
            : '尚未保存可读取的密钥。',
        },
      });
  });
  await page.route(`**/api/providers/${id}/test`, (route) =>
    route.fulfill({ json: { ok: false, detail: 'HTTP 401：认证失败，请重新保存有效 API 密钥。' } }),
  );
  await page.route(`**/api/providers/${id}/models`, (route) =>
    route.fulfill({ json: { models: ['fixture-discovered'] } }),
  );
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '⚙ 模型与设置' }).click();
  await page.getByRole('button', { name: '＋ 新建模型配置' }).click();
  await page.getByLabel('配置 ID', { exact: true }).fill(id);
  await expect(page.getByRole('button', { name: '保存配置', exact: true })).toBeDisabled();
  await page.getByLabel('模型 ID', { exact: true }).fill('fixture-model');
  await page.getByLabel('显示名称', { exact: true }).fill('UI 模型删除测试');
  await page.getByLabel('API 密钥（只保存到 Windows 凭据存储）').fill('synthetic-ui-secret');
  await page.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect(page.getByLabel('API 密钥（只保存到 Windows 凭据存储）')).toHaveValue('');
  await expect(
    page.getByText('密钥已保存，输入框留空表示保留；不会回显密钥。', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '保存配置', exact: true }).click();
  await page.getByRole('button', { name: '获取已保存配置的模型列表', exact: true }).click();
  await page.getByRole('button', { name: 'fixture-discovered', exact: true }).click();
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('fixture-discovered');
  await page.getByRole('button', { name: '保存配置', exact: true }).click();
  await page.getByRole('button', { name: '连接测试', exact: true }).click();
  await expect(page.getByText(/测试失败：HTTP 401/)).toBeVisible();
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByLabel('当前模型').selectOption(id);
  await page.getByRole('button', { name: '⚙ 模型与设置' }).click();
  await page.getByRole('button', { name: 'UI 模型删除测试', exact: true }).click();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: '删除模型配置', exact: true }).click();
  await expect(page.getByRole('button', { name: 'UI 模型删除测试', exact: true })).toHaveCount(0);

  const before = await page.locator('.sidebar .nav').filter({ hasText: '◌' }).count();
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await expect(page.locator('.sidebar .nav').filter({ hasText: '◌' })).toHaveCount(before + 1);
  await page.locator('.session-row.selected .session-more').click();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('menuitem', { name: '删除对话', exact: true }).click();
  await expect(page.locator('.sidebar .nav').filter({ hasText: '◌' })).toHaveCount(before);
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('真实 UI：添加验收检查、执行中补充、恢复不重写', async ({ page }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByRole('button', { name: /验证 coding 闭环/ }).click();
  await page.getByLabel('权限模式').selectOption('workspace');
  await page.getByRole('button', { name: '＋ 添加验收检查' }).click();
  await page.getByLabel('检查名称').fill('问候程序真实存在');
  await page.getByLabel('检查文件路径').fill('hello_agent.py');
  await page.getByRole('button', { name: '保存计划' }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('heading', { name: '需要你的授权：terminal.run' }).waitFor();
  await page.getByLabel('消息').fill('保留已生成的文件，继续运行测试并检查文件存在');
  await page.getByRole('button', { name: '提交反馈' }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('计划就绪');
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('heading', { name: '需要你的授权：terminal.run' }).waitFor();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await page.getByRole('button', { name: '接受结果' }).waitFor();
  await page.locator('.turn-records>summary').last().click();
  await page.getByRole('heading', { name: '实际验收报告' }).waitFor();
  await expect(page.getByText('问候程序真实存在：通过', { exact: true })).toBeVisible();
  await expect(
    page.locator('.turn-records details.result>summary').filter({ hasText: 'files.write' }),
  ).toHaveCount(1);
  await page.screenshot({ path: 'test-results/verification.png', fullPage: true });
  await page.getByRole('button', { name: '接受结果' }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('已完成');
});

test('真实 UI：审查中断副作用后跳过，不重复执行', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (await request.post('/api/sessions', { headers, data: { title: '恢复验收' } })).json()
  ).id;
  const script = [
    {
      name: 'terminal.run',
      arguments: {
        argv: [
          process.env.AGENT_PYTHON || 'python',
          '-c',
          "from pathlib import Path;import time;p=Path('effect.txt');p.write_text('one');print('SIDE_EFFECT_WRITTEN',flush=True);time.sleep(10)",
        ],
      },
    },
  ];
  const task = await (
    await request.post(`/api/sessions/${sid}/tasks`, {
      headers,
      data: {
        goal: '中断恢复界面验收',
        workspace: '',
        deliverables: ['effect.txt'],
        acceptance: ['仅执行一次'],
        script,
      },
    })
  ).json();
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 恢复验收', exact: true }).click();
  await page.getByRole('button', { name: /中断恢复界面验收/ }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await page.locator('.inspector summary').filter({ hasText: '实时终端输出' }).click();
  await expect(page.locator('.inspector details[open]>pre')).toContainText('SIDE_EFFECT_WRITTEN');
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await page.getByRole('heading', { name: '审查中断操作：terminal.run' }).waitFor();
  await expect(page.getByRole('button', { name: '已审查，跳过此步骤' })).toBeDisabled();
  await page.getByLabel('审查说明').fill('检查 effect.txt，已写入一次，保留当前结果');
  await page.getByRole('button', { name: '已审查，跳过此步骤' }).click();
  await expect(page.getByRole('heading', { name: '审查中断操作：terminal.run' })).toHaveCount(0);
  await page.getByRole('button', { name: '编辑计划 / 继续' }).click();
  await page.getByRole('button', { name: '保存计划' }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('button', { name: '接受结果' }).waitFor();
  const calls = await (await request.get(`/api/tasks/${task.id}/calls`, { headers })).json();
  expect(calls).toHaveLength(1);
  expect(calls[0].status).toBe('interrupted');
  expect(calls[0].decision).toBe('skip');
  await page.getByRole('button', { name: '接受结果' }).click();
});

test('真实 UI：明确批准本任务相同参数，再撤销规则', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (await request.post('/api/sessions', { headers, data: { title: '授权规则验收' } })).json()
  ).id;
  const action = {
    name: 'terminal.run',
    arguments: { argv: [process.env.AGENT_PYTHON || 'python', '-c', "print('EXACT_PERMISSION')"] },
  };
  await request.post(`/api/sessions/${sid}/tasks`, {
    headers,
    data: {
      goal: '相同参数授权验收',
      workspace: '',
      deliverables: ['命令输出'],
      acceptance: ['两次相同命令成功'],
      script: [action, action],
    },
  });
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 授权规则验收', exact: true }).click();
  await page.getByRole('button', { name: /相同参数授权验收/ }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByLabel('批准范围').selectOption('task');
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await page.getByRole('button', { name: '接受结果' }).waitFor();
  await expect(page.locator('.result pre').filter({ hasText: 'EXACT_PERMISSION' })).toHaveCount(2);
  await page.getByRole('button', { name: '接受结果' }).click();
  await page.getByRole('button', { name: '⚙ 模型与设置' }).click();
  const rule = page
    .locator('.row')
    .filter({ has: page.getByText('具体规则', { exact: true }) })
    .filter({ hasText: 'EXACT_PERMISSION' })
    .first();
  await rule.getByRole('button', { name: '撤销', exact: true }).click();
  await expect(rule).toContainText('已撤销 / 已消费');
});
test('真实 UI：计划、授权、执行、产物与验收', async ({ page }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByRole('button', { name: /验证 coding 闭环/ }).click();
  await page.getByRole('button', { name: '保存计划' }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await expect(page.getByRole('heading', { name: '需要你的授权：files.write' })).toBeVisible();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await expect(page.getByRole('heading', { name: '需要你的授权：terminal.run' })).toBeVisible();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await expect(page.getByRole('button', { name: '接受结果' })).toBeVisible();
  await page.locator('.turn-records>summary').click();
  await page
    .locator('.turn-records details.result>summary')
    .filter({ hasText: 'terminal.run' })
    .click();
  await expect(
    page.locator('details.result[open] pre').filter({ hasText: 'PASS: greet verified' }),
  ).toBeVisible();
  const dl = page.waitForEvent('download');
  await page
    .getByRole('region', { name: '任务成果' })
    .getByRole('button', { name: '下载', exact: true })
    .click();
  expect((await dl).suggestedFilename()).toBe('hello_agent.py');
  await page.getByRole('button', { name: '接受结果' }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('已完成');
  await page.screenshot({ path: 'test-results/workbench.png', fullPage: true });
});
test('真实 UI：暂停、修改计划、拒绝', async ({ page }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByRole('button', { name: /验证 coding 闭环/ }).click();
  await page.getByRole('button', { name: '保存计划' }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await expect(page.getByRole('button', { name: '批准这次操作' })).toBeVisible();
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('已暂停');
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByRole('button', { name: /验证 coding 闭环/ }).click();
  await page.getByRole('button', { name: '保存计划' }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('button', { name: '拒绝', exact: true }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('需要你处理');
});
test('真实 UI：附件、记忆、扩展配置与反馈', async ({ page }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.locator('input[type=file]').setInputFiles({
    name: 'notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Attachment proof'),
  });
  await expect(page.getByRole('button', { name: 'notes.txt ×' })).toBeVisible();
  await page.getByRole('button', { name: '◇ 长期记忆' }).click();
  await page.getByLabel('记忆内容').fill('E2E memory proof');
  await page.getByRole('button', { name: '保存记忆' }).click();
  await expect(page.locator('.result').filter({ hasText: 'E2E memory proof' })).toBeVisible();
  await page
    .locator('.result')
    .filter({ hasText: 'E2E memory proof' })
    .getByRole('button', { name: '删除' })
    .click();
  await expect(page.locator('.result').filter({ hasText: 'E2E memory proof' })).toHaveCount(0);
  await page.getByRole('button', { name: '⊞ 扩展与自动化' }).click();
  await page.getByRole('button', { name: '服务连接' }).click();
  await expect(page.getByRole('heading', { name: '连接外部服务' })).toBeVisible();
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await page.getByRole('button', { name: /验证 coding 闭环/ }).click();
  await page.getByRole('button', { name: '保存计划' }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await page.getByRole('heading', { name: '需要你的授权：terminal.run' }).waitFor();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await page.getByRole('button', { name: '接受结果' }).waitFor();
  await page.getByLabel('消息').fill('请增加一个测试用例');
  await page.getByRole('button', { name: '提交反馈' }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('计划就绪');
  await page.getByRole('button', { name: '编辑计划 / 继续' }).click();
  await expect(page.getByLabel('上下文与补充说明')).toContainText('请增加一个测试用例');
});

test('多轮时间线按用户、思考记录、回复排序且输入框不显示任务失败', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (
      await request.post('/api/sessions', { headers, data: { title: '时间线顺序测试' } })
    ).json()
  ).id;
  const boot = await (await request.get('/api/bootstrap', { headers })).json();
  const spec = {
    conversational: true,
    goal: '顺序测试',
    workspace: '',
    plan: [],
    acceptance: [],
    deliverables: [],
    tools: [],
    provider: 'scripted',
    mode: 'workspace',
    collaboration: false,
  };
  const tasks = [
    { id: 'timeline-a', session_id: sid, created: 11, updated: 14, state: 'failed', spec },
    { id: 'timeline-b', session_id: sid, created: 21, updated: 24, state: 'failed', spec },
  ];
  await page.route('**/api/bootstrap', (r) =>
    r.fulfill({ json: { ...boot, tasks: [...tasks].reverse() } }),
  );
  await page.route(`**/api/sessions/${sid}/messages`, (r) =>
    r.fulfill({
      json: [
        { id: 'u1', role: 'user', content: '第一轮问题', created: 10 },
        { id: 'a1', role: 'assistant', content: '第一轮回答', created: 14 },
        { id: 'u2', role: 'user', content: '第二轮问题', created: 20 },
        { id: 'a2', role: 'assistant', content: '第二轮回答', created: 24 },
      ],
    }),
  );
  for (const t of tasks) {
    await page.route(`**/api/tasks/${t.id}/events*`, (r) =>
      r.fulfill({
        json: [
          {
            id: t.created,
            task_id: t.id,
            type: 'reasoning',
            created: t.created + 1,
            payload: { text: '思考 ' + t.id },
          },
        ],
      }),
    );
    await page.route(`**/api/tasks/${t.id}/calls`, (r) =>
      r.fulfill({
        json: [
          {
            id: t.id,
            created: t.created + 1,
            tool: 'files.write',
            status: 'succeeded',
            result: { stdout: '本轮记录' },
          },
        ],
      }),
    );
    await page.route(`**/api/tasks/${t.id}/result`, (r) =>
      r.fulfill({
        json: {
          usage: {
            requests: 1,
            input_tokens: 1,
            output_tokens: 1,
            estimated: false,
            unknown_cost_requests: 1,
          },
          planned_deliverables: [],
          artifacts: [],
        },
      }),
    );
  }
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 时间线顺序测试', exact: true }).click();
  await expect(page.locator('.turn-execution')).toHaveCount(2);
  const order = await page
    .locator('.chat-area')
    .evaluate((el) =>
      Array.from(el.querySelectorAll('.message:not(.failure-reply),.turn-execution')).map(
        (e) => e.getAttribute('data-task-id') || e.textContent,
      ),
    );
  expect(order[0]).toContain('第一轮问题');
  expect(order[1]).toBe('timeline-a');
  expect(order[2]).toContain('第一轮回答');
  expect(order[3]).toContain('第二轮问题');
  expect(order[4]).toBe('timeline-b');
  expect(order[5]).toContain('第二轮回答');
  await expect(page.locator('.turn-records[open]')).toHaveCount(0);
  await page.locator('.turn-records>summary').first().click();
  await expect(page.locator('.turn-records[open]')).toHaveCount(1);
  await expect(page.locator('.composer .execution-state')).toHaveText('需要用户操作');
  await page.screenshot({ path: 'test-results/conversation-timeline.png', fullPage: true });
});

test('界面更新提示保留会话与草稿，终端输出默认折叠', async ({ page }) => {
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '＋ 新建会话' }).click();
  await expect(page.getByText('界面 0.7.2', { exact: true })).toBeVisible();
  await page.getByLabel('消息', { exact: true }).fill('尚未发送的草稿');
  await expect(page.locator('.inspector details[open]')).toHaveCount(0);
  await page.route('**/?ui-check=*', (r) =>
    r.fulfill({
      contentType: 'text/html',
      body: '<script type="module" src="/assets/new-interface.js"></script>',
    }),
  );
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.getByRole('button', { name: '发现新版界面 · 保留草稿并刷新' }).click();
  await expect(page.getByLabel('消息', { exact: true })).toHaveValue('尚未发送的草稿');
  await expect(page.locator('.session-row.selected')).toHaveCount(1);
});

test('浏览器接管仅在执行详情，工具错误不会判定整体任务失败', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (await request.post('/api/sessions', { headers, data: { title: '失败反馈测试' } })).json()
  ).id;
  const t = await (
    await request.post(`/api/sessions/${sid}/tasks`, {
      headers,
      data: {
        goal: '失败原因回显',
        workspace: '',
        deliverables: ['报告'],
        acceptance: ['验证'],
        tools: ['browser.action', 'terminal.run'],
        script: [
          { name: 'terminal.run', arguments: { argv: ['not-a-real-executable-for-ui-test'] } },
        ],
      },
    })
  ).json();
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 失败反馈测试', exact: true }).click();
  await expect(
    page.locator('.inspector').getByRole('heading', { name: '浏览器接管' }),
  ).toBeVisible();
  await expect(page.locator('.chat-area').getByRole('heading', { name: '浏览器接管' })).toHaveCount(
    0,
  );
  await page.getByRole('button', { name: '开始执行' }).click();
  await page.getByRole('button', { name: '批准这次操作' }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('等待验收');
  await expect(page.getByLabel('执行中止原因')).toHaveCount(0);
  await expect(page.locator('.turn-records[open]')).toHaveCount(0);
  await page.reload();
  await page.getByRole('button', { name: '◌ 失败反馈测试', exact: true }).click();
  await expect(page.locator('.task-card .pill')).toHaveText('等待验收');
  await expect(page.getByLabel('执行中止原因')).toHaveCount(0);
  await page.locator('.turn-records>summary').click();
  await page.locator('.turn-records details.result>summary').first().click();
  await expect(page.locator('.turn-records')).toContainText('FileNotFoundError');
  await page.screenshot({ path: 'test-results/failure-conversation.png', fullPage: true });
});
test('上下文预算与压缩记录可见且默认折叠', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (
      await request.post('/api/sessions', { headers, data: { title: '上下文压缩测试' } })
    ).json()
  ).id;
  const boot = await (await request.get('/api/bootstrap', { headers })).json();
  const spec = {
    conversational: true,
    goal: '压缩回归',
    workspace: '',
    plan: [],
    acceptance: [],
    deliverables: [],
    tools: [],
    provider: 'scripted',
    mode: 'workspace',
    collaboration: false,
  };
  const task = {
    id: 'context-test',
    session_id: sid,
    created: 11,
    updated: 600,
    state: 'waiting_for_user',
    state_detail: '相同操作重复得到相同结果，请审查无进展循环',
    timing: { started: 11, ended: 600 },
    spec,
  };
  const info = {
    before_tokens: 150000,
    input_tokens: 9000,
    input_limit: 31808,
    output_reserve: 8192,
    source: 'local_fallback',
    checkpoint: '本地结构化上下文摘要：render.cpp 已写入；未授权额外操作。',
  };
  await page.route('**/api/bootstrap', (r) =>
    r.fulfill({
      json: { ...boot, sessions: boot.sessions.filter((s: any) => s.id === sid), tasks: [task] },
    }),
  );
  await page.route(`**/api/sessions/${sid}/messages`, (r) =>
    r.fulfill({
      json: [
        { id: 'u1', role: 'user', content: '创建 render', created: 10 },
        { id: 'a1', role: 'assistant', content: '文件已完成', created: 14 },
      ],
    }),
  );
  await page.route('**/api/tasks/context-test/events*', (r) =>
    r.fulfill({
      json: [
        { id: 1, type: 'context_compacted', created: 12, payload: info },
        { id: 2, type: 'context_budget', created: 13, payload: info },
      ],
    }),
  );
  await page.route('**/api/tasks/context-test/calls', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/tasks/context-test/result', (r) =>
    r.fulfill({
      json: {
        usage: { requests: 1, input_tokens: 9000, output_tokens: 100, unknown_cost_requests: 1 },
        planned_deliverables: [],
        artifacts: [],
      },
    }),
  );
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 上下文压缩测试', exact: true }).click();
  await expect(page.getByLabel('上下文与执行状态')).toContainText('已压缩');
  await expect(page.locator('.context-indicator')).not.toHaveAttribute('open', '');
  await page.getByLabel('上下文占用', { exact: true }).click();
  await expect(page.locator('.context-popover')).toContainText('输入预算 31,808 / 输出预留 8,192');
  await expect(page.locator('.context-compaction')).not.toHaveAttribute('open', '');
  await expect(page.locator('.composer .execution-state')).toBeVisible();
  const within = await page.locator('.composer .execution-state').evaluate((el) => {
    const a = el.getBoundingClientRect(),
      b = el.closest('.composer')!.getBoundingClientRect();
    return a.right <= b.right && a.left >= b.left;
  });
  expect(within).toBe(true);
  await page.locator('.context-compaction summary').click();
  await expect(page.locator('.context-compaction pre')).toContainText('render.cpp');
  await expect(page.getByLabel('执行过程')).toContainText('总用时 9 分 49 秒');
  await expect(page.getByLabel('需要用户操作的原因')).toContainText('相同操作重复得到相同结果');
  await expect(page.getByLabel('需要用户操作的原因')).toContainText('补充修正方向');
  await page.screenshot({ path: 'test-results/context-compaction.png', fullPage: true });
});

test('工具错误达到上限时对话显示原因和介入操作，刷新后保留', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer ' + token() };
  const sid = (
    await (await request.post('/api/sessions', { headers, data: { title: '错误上限测试' } })).json()
  ).id;
  await request.post(`/api/sessions/${sid}/tasks`, {
    headers,
    data: {
      goal: '错误计数',
      workspace: '',
      deliverables: ['结果'],
      acceptance: ['检查输出'],
      mode: 'workspace',
      tools: ['files.read'],
      script: [1, 2, 3, 4].map((i) => ({
        name: 'files.read',
        arguments: { path: `absent-${i}.txt` },
      })),
    },
  });
  await page.goto('/#token=' + token());
  await page.getByRole('button', { name: '◌ 错误上限测试', exact: true }).click();
  await page.getByRole('button', { name: '开始执行' }).click();
  const reason = page.getByLabel('需要用户操作的原因');
  await expect(reason).toContainText('3/3');
  await expect(reason).toContainText('absent-3.txt');
  await expect(reason).toContainText('编辑计划 / 继续');
  await expect(page.locator('.task-card .pill')).toHaveText('需要你处理');
  await expect(page.locator('.composer .execution-state')).toHaveText('需要用户操作');
  await expect(page.locator('.turn-records[open]')).toHaveCount(0);
  await expect(page.locator('.turn-records>summary')).toContainText('3 次工具操作');
  await page.reload();
  await page.getByRole('button', { name: '◌ 错误上限测试', exact: true }).click();
  await expect(page.getByLabel('需要用户操作的原因')).toContainText('3/3');
  await expect(page.getByText('任务失败', { exact: true })).toHaveCount(0);
});
