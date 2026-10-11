import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const data=process.env.AGENT_DATA||path.resolve('data');
const token=()=>fs.readFileSync(path.join(data,'client.token'),'utf8').trim();

test('安全富文本：代码块、复制、HTML 和危险链接不执行',async({page,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);
 await page.route('**/api/sessions/*/chat',route=>route.fulfill({json:{content:'**说明**\n```python\nassert 1 + 1 == 2\n```\n<script>window.agentInjected=true</script>\n[危险](javascript:alert(1))\n[来源](https://example.com)'}}));
 await page.goto('/#token='+token());await page.getByRole('button',{name:'＋ 新建会话'}).click();
 // Use persisted messages: the application reloads history after chat requests.
 const headers={Authorization:'Bearer '+token()};
 const response=await page.request.get('/api/bootstrap',{headers});const sid=(await response.json()).sessions[0].id;
 await page.route(`**/api/sessions/${sid}/messages`,route=>route.fulfill({json:[{id:'fixture',role:'assistant',content:'**说明**\n```python\nassert 1 + 1 == 2\n```\n<script>window.agentInjected=true</script>\n[危险](javascript:alert(1))\n[来源](https://example.com)'}]}));
 await page.getByLabel('消息').fill('展示格式');await page.getByRole('button',{name:'发送问答'}).click();
 await expect(page.locator('.message pre code')).toHaveText('assert 1 + 1 == 2');
 await page.getByRole('button',{name:'复制代码',exact:true}).click();await expect(page.getByRole('button',{name:'已复制',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe('assert 1 + 1 == 2');
 await expect(page.locator('.message script')).toHaveCount(0);await expect(page.locator('.message a[href^="javascript:"]')).toHaveCount(0);
 expect(await page.evaluate(()=>(window as any).agentInjected)).toBeUndefined();
 await expect(page.getByRole('link',{name:'来源'})).toHaveAttribute('rel','noopener noreferrer');
 await page.screenshot({path:'test-results/rich-text.png',fullPage:true});
});

test('记忆版本、导出和技能应用只生成待审查计划',async({page,request})=>{
 await page.goto('/#token='+token());await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await page.getByRole('button',{name:'◇ 长期记忆'}).click();await page.getByLabel('记忆内容').fill('旧版决定 alpha');await page.getByRole('button',{name:'保存记忆'}).click();
 const item=page.locator('.result').filter({hasText:'旧版决定 alpha'});await item.getByRole('button',{name:'编辑',exact:true}).click();
 await page.getByLabel('记忆内容').fill('新版决定 beta');await page.getByRole('button',{name:'保存记忆'}).click();
 const updated=page.locator('.result').filter({hasText:'新版决定 beta'});await updated.getByRole('button',{name:'版本历史'}).click();
 await expect(page.getByRole('heading',{name:'编辑前的历史版本'})).toBeVisible();await expect(page.locator('pre').filter({hasText:'旧版决定 alpha'})).toBeVisible();
 const dl=page.waitForEvent('download');await page.getByRole('button',{name:'导出全部记忆'}).click();expect((await dl).suggestedFilename()).toBe('agent-memories.json');
 await updated.getByRole('button',{name:'删除',exact:true}).click();await expect(page.locator('pre').filter({hasText:'旧版决定 alpha'})).toHaveCount(0);
 await page.getByRole('button',{name:'⊞ 扩展与自动化'}).click();await page.getByRole('button',{name:'项目检查',exact:true}).click();
 const headers={Authorization:'Bearer '+token()},before=(await (await request.get('/api/bootstrap',{headers})).json()).tasks.length;
 await page.getByRole('button',{name:'使用此技能创建计划'}).click();await expect(page.getByRole('heading',{name:'把需求变成可执行计划'})).toBeVisible();
 await expect(page.getByRole('textbox',{name:'执行计划',exact:true})).toHaveValue(/files.list/);
 await expect(page.getByRole('textbox',{name:'上下文与补充说明',exact:true})).toHaveValue(/source_id/);
 const after=await (await request.get('/api/bootstrap',{headers})).json();expect(after.tasks.length).toBe(before);
});

test('设置修复：空模型拦截、密钥状态、错误提示、删除模型和会话',async({page})=>{
 const id='ui_settings_'+Date.now();let stored=false;
 await page.route(`**/api/providers/${id}/credential`,async route=>{
  if(route.request().method()==='POST'){stored=true;await route.fulfill({json:{ok:true}})}
  else await route.fulfill({json:{saved:stored,detail:stored?'密钥已保存，输入框留空表示保留；不会回显密钥。':'尚未保存可读取的密钥。'}});
 });
 await page.route(`**/api/providers/${id}/test`,route=>route.fulfill({json:{ok:false,detail:'HTTP 401：认证失败，请重新保存有效 API 密钥。'}}));
 await page.route(`**/api/providers/${id}/models`,route=>route.fulfill({json:{models:['fixture-discovered']}}));
 await page.goto('/#token='+token());await page.getByRole('button',{name:'⚙ 模型与设置'}).click();
 await page.getByRole('button',{name:'＋ 新建模型配置'}).click();await page.getByLabel('配置 ID',{exact:true}).fill(id);
 await expect(page.getByRole('button',{name:'保存配置',exact:true})).toBeDisabled();
 await page.getByLabel('模型 ID',{exact:true}).fill('fixture-model');await page.getByLabel('显示名称',{exact:true}).fill('UI 模型删除测试');
 await page.getByLabel('API 密钥（只保存到 Windows 凭据存储）').fill('synthetic-ui-secret');
 await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await expect(page.getByLabel('API 密钥（只保存到 Windows 凭据存储）')).toHaveValue('');
 await expect(page.getByText('密钥已保存，输入框留空表示保留；不会回显密钥。',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await page.getByRole('button',{name:'获取已保存配置的模型列表',exact:true}).click();
 await page.getByRole('button',{name:'fixture-discovered',exact:true}).click();
 await expect(page.getByLabel('模型 ID',{exact:true})).toHaveValue('fixture-discovered');
 await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await page.getByRole('button',{name:'连接测试',exact:true}).click();await expect(page.getByText(/测试失败：HTTP 401/)).toBeVisible();
 await page.getByLabel('当前模型').selectOption(id);
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'删除模型配置',exact:true}).click();
 await expect(page.getByRole('button',{name:'UI 模型删除测试',exact:true})).toHaveCount(0);
 await expect(page.getByLabel('当前模型')).toHaveValue('scripted');
 const before=await page.locator('.sidebar .nav').filter({hasText:'◌'}).count();
 await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await expect(page.locator('.sidebar .nav').filter({hasText:'◌'})).toHaveCount(before+1);
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'删除当前会话',exact:true}).click();
 await expect(page.locator('.sidebar .nav').filter({hasText:'◌'})).toHaveCount(before);
 await expect(page.getByRole('alert')).toHaveCount(0);
});

test('真实 UI：添加验收检查、执行中补充、恢复不重写',async({page})=>{
 await page.goto('/#token='+token());await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await page.getByRole('button',{name:/验证 coding 闭环/}).click();
 await page.getByLabel('权限模式').selectOption('workspace');
 await page.getByRole('button',{name:'＋ 添加验收检查'}).click();
 await page.getByLabel('检查名称').fill('问候程序真实存在');
 await page.getByLabel('检查文件路径').fill('hello_agent.py');
 await page.getByRole('button',{name:'保存计划'}).click();await page.getByRole('button',{name:'开始执行'}).click();
 await page.getByRole('heading',{name:'需要你的授权：terminal.run'}).waitFor();
 await page.getByLabel('消息').fill('保留已生成的文件，继续运行测试并检查文件存在');
 await page.getByRole('button',{name:'提交反馈'}).click();
 await expect(page.locator('.task-card .pill')).toHaveText('计划就绪');
 await page.getByRole('button',{name:'开始执行'}).click();
 await page.getByRole('heading',{name:'需要你的授权：terminal.run'}).waitFor();await page.getByRole('button',{name:'批准这次操作'}).click();
 await page.getByRole('heading',{name:'实际验收报告'}).waitFor();
 await expect(page.getByText('问候程序真实存在：通过',{exact:true})).toBeVisible();
 await expect(page.locator('.result b').filter({hasText:'files.write'})).toHaveCount(1);
 await page.screenshot({path:'test-results/verification.png',fullPage:true});
 await page.getByRole('button',{name:'接受结果'}).click();
 await expect(page.locator('.task-card .pill')).toHaveText('已完成');
});

test('真实 UI：审查中断副作用后跳过，不重复执行',async({page,request})=>{
 const headers={Authorization:'Bearer '+token()};
 const sid=(await (await request.post('/api/sessions',{headers,data:{title:'恢复验收'}})).json()).id;
 const script=[{name:'terminal.run',arguments:{argv:[process.env.AGENT_PYTHON||'python','-c',"from pathlib import Path;import time;p=Path('effect.txt');p.write_text('one');print('SIDE_EFFECT_WRITTEN',flush=True);time.sleep(10)"]}}];
 const task=await (await request.post(`/api/sessions/${sid}/tasks`,{headers,data:{goal:'中断恢复界面验收',workspace:'',deliverables:['effect.txt'],acceptance:['仅执行一次'],script}})).json();
 await page.goto('/#token='+token());await page.getByRole('button',{name:/中断恢复界面验收/}).click();
 await page.getByRole('button',{name:'开始执行'}).click();await page.getByRole('button',{name:'批准这次操作'}).click();
 await expect(page.locator('.inspector>pre')).toContainText('SIDE_EFFECT_WRITTEN');
 await page.getByRole('button',{name:'暂停',exact:true}).click();
 await page.getByRole('heading',{name:'审查中断操作：terminal.run'}).waitFor();
 await expect(page.getByRole('button',{name:'已审查，跳过此步骤'})).toBeDisabled();
 await page.getByLabel('审查说明').fill('检查 effect.txt，已写入一次，保留当前结果');
 await page.getByRole('button',{name:'已审查，跳过此步骤'}).click();
 await expect(page.getByRole('heading',{name:'审查中断操作：terminal.run'})).toHaveCount(0);
 await page.getByRole('button',{name:'编辑计划 / 继续'}).click();await page.getByRole('button',{name:'保存计划'}).click();
 await page.getByRole('button',{name:'开始执行'}).click();await page.getByRole('button',{name:'接受结果'}).waitFor();
 const calls=await (await request.get(`/api/tasks/${task.id}/calls`,{headers})).json();
 expect(calls).toHaveLength(1);expect(calls[0].status).toBe('interrupted');expect(calls[0].decision).toBe('skip');
 await page.getByRole('button',{name:'接受结果'}).click();
});

test('真实 UI：明确批准本任务相同参数，再撤销规则',async({page,request})=>{
 const headers={Authorization:'Bearer '+token()};const sid=(await (await request.post('/api/sessions',{headers,data:{title:'授权规则验收'}})).json()).id;
 const action={name:'terminal.run',arguments:{argv:[process.env.AGENT_PYTHON||'python','-c',"print('EXACT_PERMISSION')"]}};
 await request.post(`/api/sessions/${sid}/tasks`,{headers,data:{goal:'相同参数授权验收',workspace:'',deliverables:['命令输出'],acceptance:['两次相同命令成功'],script:[action,action]}});
 await page.goto('/#token='+token());await page.getByRole('button',{name:/相同参数授权验收/}).click();await page.getByRole('button',{name:'开始执行'}).click();
 await page.getByLabel('批准范围').selectOption('task');await page.getByRole('button',{name:'批准这次操作'}).click();
 await page.getByRole('button',{name:'接受结果'}).waitFor();await expect(page.locator('.result pre').filter({hasText:'EXACT_PERMISSION'})).toHaveCount(2);
 await page.getByRole('button',{name:'接受结果'}).click();await page.getByRole('button',{name:'⚙ 模型与设置'}).click();
 const rule=page.locator('.row').filter({has:page.getByText('具体规则',{exact:true})}).filter({hasText:'EXACT_PERMISSION'}).first();
 await rule.getByRole('button',{name:'撤销',exact:true}).click();await expect(rule).toContainText('已撤销 / 已消费');
});
test('真实 UI：计划、授权、执行、产物与验收',async({page})=>{
 await page.goto('/#token='+token());
 await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await page.getByRole('button',{name:/验证 coding 闭环/}).click();
 await page.getByRole('button',{name:'保存计划'}).click();
 await page.getByRole('button',{name:'开始执行'}).click();
 await expect(page.getByRole('heading',{name:'需要你的授权：files.write'})).toBeVisible();
 await page.getByRole('button',{name:'批准这次操作'}).click();
 await expect(page.getByRole('heading',{name:'需要你的授权：terminal.run'})).toBeVisible();
 await page.getByRole('button',{name:'批准这次操作'}).click();
 await expect(page.getByRole('button',{name:'接受结果'})).toBeVisible();
 await expect(page.locator('.result pre').filter({hasText:'PASS: greet verified'})).toBeVisible();
 const dl=page.waitForEvent('download');await page.getByRole('button',{name:'↓ hello_agent.py'}).click();
 expect((await dl).suggestedFilename()).toBe('hello_agent.py');
 await page.getByRole('button',{name:'接受结果'}).click();
 await expect(page.locator('.task-card .pill')).toHaveText('已完成');
 await page.screenshot({path:'test-results/workbench.png',fullPage:true});
});
test('真实 UI：暂停、修改计划、拒绝',async({page})=>{
 await page.goto('/#token='+token());await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await page.getByRole('button',{name:/验证 coding 闭环/}).click();await page.getByRole('button',{name:'保存计划'}).click();await page.getByRole('button',{name:'开始执行'}).click();
 await expect(page.getByRole('button',{name:'批准这次操作'})).toBeVisible();await page.getByRole('button',{name:'暂停',exact:true}).click();
 await expect(page.locator('.task-card .pill')).toHaveText('已暂停');
 await page.getByRole('button',{name:'＋ 新建会话'}).click();await page.getByRole('button',{name:/验证 coding 闭环/}).click();await page.getByRole('button',{name:'保存计划'}).click();await page.getByRole('button',{name:'开始执行'}).click();
 await page.getByRole('button',{name:'拒绝',exact:true}).click();await expect(page.locator('.task-card .pill')).toHaveText('失败');
});
test('真实 UI：附件、记忆、扩展配置与反馈',async({page})=>{
 await page.goto('/#token='+token());await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await page.locator('input[type=file]').setInputFiles({name:'notes.txt',mimeType:'text/plain',buffer:Buffer.from('Attachment proof')});
 await expect(page.getByRole('button',{name:'notes.txt ×'})).toBeVisible();
 await page.getByRole('button',{name:'◇ 长期记忆'}).click();
 await page.getByLabel('记忆内容').fill('E2E memory proof');await page.getByRole('button',{name:'保存记忆'}).click();
 await expect(page.locator('.result').filter({hasText:'E2E memory proof'})).toBeVisible();
 await page.locator('.result').filter({hasText:'E2E memory proof'}).getByRole('button',{name:'删除'}).click();
 await expect(page.locator('.result').filter({hasText:'E2E memory proof'})).toHaveCount(0);
 await page.getByRole('button',{name:'⊞ 扩展与自动化'}).click();await page.getByRole('button',{name:'服务连接'}).click();
 await expect(page.getByRole('heading',{name:'连接外部服务'})).toBeVisible();
 await page.getByRole('button',{name:'＋ 新建会话'}).click();
 await page.getByRole('button',{name:/验证 coding 闭环/}).click();await page.getByRole('button',{name:'保存计划'}).click();await page.getByRole('button',{name:'开始执行'}).click();
 await page.getByRole('button',{name:'批准这次操作'}).click();await page.getByRole('heading',{name:'需要你的授权：terminal.run'}).waitFor();await page.getByRole('button',{name:'批准这次操作'}).click();
 await page.getByRole('button',{name:'接受结果'}).waitFor();await page.getByLabel('消息').fill('请增加一个测试用例');await page.getByRole('button',{name:'提交反馈'}).click();
 await expect(page.locator('.task-card .pill')).toHaveText('计划就绪');
 await page.getByRole('button',{name:'编辑计划 / 继续'}).click();await expect(page.getByLabel('上下文与补充说明')).toContainText('请增加一个测试用例');
});
