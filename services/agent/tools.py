import asyncio, difflib, hashlib, json, os, time
from pathlib import Path
import psutil
from pydantic import Field
from .models import Strict, FileRead, FileWrite, Command,Revert,GitCommit,AcceptanceCheck
from .store import uid
from .policy import inside
from .extensions import BrowserArgs, BrowserTools, DesktopArgs, DesktopTools
from .integrations import SearchArgs,search,EmailArgs,send_email

class Empty(Strict): pass
class Document(Strict):
    path: str
    content: str | None = None
class Fetch(Strict):
    url: str
class MCPCall(Strict):
    transport: str = 'stdio'
    command: str = ''
    args: list[str] = []
    url: str = ''
    tool: str = ''
    arguments: dict = {}

SCHEMAS={'files.read':FileRead,'files.write':FileWrite,'files.list':Empty,'terminal.run':Command,
         'git.diff':Empty,'document.process':Document,'web.fetch':Fetch,'mcp.call':MCPCall,
         'browser.action':BrowserArgs,'desktop.action':DesktopArgs,'web.search':SearchArgs,'email.send':EmailArgs,
         'files.revert':Revert,'git.status':Empty,'git.commit':GitCommit,'checks.run':AcceptanceCheck}
DESCRIPTIONS={
    'files.read':'Read UTF-8 file within workspace; returns hash required for overwrite.',
    'files.write':'Create or replace UTF-8 file. Existing file requires matching expected_sha256.',
    'files.list':'List top-level workspace entries.',
    'terminal.run':'Execute argv WITHOUT OS sandbox. Can access outside workspace. Requires explicit authorization.',
    'git.diff':'Read git diff; no commits.',
    'document.process':'Read or create txt/md/json/csv/docx/xlsx/pdf. Existing outputs require explicit approval.',
    'web.fetch':'Fetch public HTTP(S) page, preserving source URL and retrieval time. No search provider included.',
    'mcp.call':'Start external MCP or connect remote, discover and optionally invoke tool; opaque capability needs approval.',
    'browser.action':'Independent browser. Observe before each action. Submit requires separate action and explicit approval.',
    'desktop.action':'Windows UIA. Human must arm control. Each input requires fresh observation, stable target and foreground. Ctrl+Alt+F12 emergency stop.',
    'web.search':'Query the user-configured real search API and preserve sources. Fails clearly when unconfigured.',
    'email.send':'Send an external email. Disabled unless user configured SMTP. Always requires exact recipient/body approval.',
    'files.revert':'Revert only a recorded change from this task, and only if the current file still matches the written hash. Requires explicit approval.',
    'git.status':'Read Git working tree status.',
    'git.commit':'Commit ONLY explicitly listed paths; may execute repository hooks, requires independent execution authorization.'}
DESCRIPTIONS['checks.run']='Run an exact user-planned acceptance check; models cannot change the approved acceptance criteria.'

def schemas(names):
    return [{'type':'function','function':{'name':n.replace('.','__'),'description':DESCRIPTIONS[n],
             'parameters':SCHEMAS[n].model_json_schema()}} for n in names if n in SCHEMAS and n!='checks.run']

def kill_tree(pid):
    try: parent=psutil.Process(pid)
    except psutil.NoSuchProcess: return
    children=parent.children(recursive=True)
    for p in reversed(children):
        try: p.kill()
        except psutil.NoSuchProcess: pass
    try: parent.kill()
    except psutil.NoSuchProcess: pass
    psutil.wait_procs(children+[parent],timeout=3)

class Tools:
    def __init__(self,store=None): self.store=store;self.processes={}; self.browser=BrowserTools(); self.desktop=DesktopTools()

    async def synchronous(self,fn,*args):
        # Keep the single executor occupied until an uninterruptible side effect settles.
        job=asyncio.create_task(asyncio.to_thread(fn,*args))
        try:return await asyncio.shield(job)
        except asyncio.CancelledError:
            await asyncio.gather(job,return_exceptions=True)
            raise

    async def execute(self, task, name, args, emit):
        name=name.replace('__','.')
        validated=SCHEMAS[name].model_validate(args).model_dump()
        root=task['spec']['workspace']; start=time.time()
        result={'status':'succeeded','started':start,'exit_code':None,'artifacts':[]}
        try:
            if name=='files.list':
                result['output']=[{'name':p.name,'directory':p.is_dir()} for p in Path(root).iterdir()][:1000]
            elif name=='files.read':
                p=inside(root,validated['path']); raw=p.read_bytes()
                if len(raw)>1_000_000: raise ValueError('文件过大，请缩小范围')
                result.update(output=raw.decode('utf-8'),sha256=hashlib.sha256(raw).hexdigest())
            elif name=='files.write':
                p=inside(root,validated['path']); old=p.read_bytes() if p.exists() else None
                if old is not None and hashlib.sha256(old).hexdigest()!=validated['expected_sha256']:
                    raise ValueError('文件已经存在或发生变化；先读取并提交匹配的 expected_sha256')
                if old is not None and len(old)>1_000_000:raise ValueError('文件过大，拒绝文本覆盖')
                old_text=old.decode('utf-8') if old is not None else None
                content=validated['content']; p.parent.mkdir(parents=True,exist_ok=True)
                # Revalidate after creating parents to detect existing junctions.
                inside(root,validated['path'])
                p.write_bytes(content.encode('utf-8'))
                if self.store:
                    change_id=uid();self.store.run('INSERT INTO changes VALUES(?,?,?,?,?,0)',(change_id,task['id'],str(p),old_text,hashlib.sha256(p.read_bytes()).hexdigest()))
                    result['change_id']=change_id
                result.update(output=f'已写入 {p.name}',artifacts=[str(p.relative_to(Path(root).resolve()))],
                    diff=''.join(difflib.unified_diff((old_text or '').splitlines(True),content.splitlines(True),fromfile=str(p),tofile=str(p))))
            elif name=='files.revert':
                if not self.store:raise ValueError('缺少变更记录存储')
                change=self.store.one('SELECT * FROM changes WHERE id=? AND task_id=?',(validated['change_id'],task['id']))
                p=inside(root,change['path'])
                if change['reverted'] or not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=change['after_sha']:raise ValueError('文件已有后续修改或已回退，不覆盖用户改动')
                if change['before_text'] is None:p.unlink()
                else:p.write_bytes(change['before_text'].encode('utf-8'))
                self.store.run('UPDATE changes SET reverted=1 WHERE id=?',(change['id'],));result['output']='仅回退了本任务记录的变更'
            elif name in ('terminal.run','git.diff','git.status','git.commit'):
                if name=='git.commit':
                    paths=[str(inside(root,p).relative_to(Path(root).resolve())) for p in validated['paths']]
                    argv=['git','commit','--only','-m',validated['message'],'--',*paths]
                elif name=='git.status':argv=['git','status','--porcelain=v1']
                else:argv=validated.get('argv',['git','--no-pager','diff','--no-ext-diff','--no-textconv'])
                result.update(await self.command(task['id'],argv,root,validated.get('timeout',30),emit))
            elif name=='document.process':
                result.update(await self.synchronous(document,root,validated))
            elif name=='web.fetch':
                import httpx, ipaddress, socket
                from urllib.parse import urlparse
                parsed=urlparse(validated['url'])
                if parsed.scheme not in ('http','https') or not parsed.hostname: raise ValueError('仅支持 HTTP(S)')
                addresses=await asyncio.to_thread(socket.getaddrinfo,parsed.hostname,None)
                if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses): raise PermissionError('禁止访问内网地址')
                async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
                    async with client.stream('GET',validated['url']) as response:
                        response.raise_for_status(); chunks=[]; size=0
                        async for chunk in response.aiter_bytes():
                            size+=len(chunk)
                            if size>2_000_000: raise ValueError('网页超出大小限制')
                            chunks.append(chunk)
                result.update(output=b''.join(chunks).decode('utf-8',errors='replace'),source={'url':validated['url'],'retrieved':time.time()})
            elif name=='mcp.call':
                result.update(output=await asyncio.wait_for(mcp_call(validated),60))
            elif name=='browser.action':
                result.update(await self.browser.run(task,validated))
            elif name=='desktop.action':
                result.update(await self.synchronous(self.desktop.run,validated))
            elif name=='web.search':
                result.update(await search(self.store,validated))
            elif name=='email.send':
                result.update(await self.synchronous(send_email,self.store,validated))
            elif name=='checks.run':
                from .verification import perform_check
                result.update(await perform_check(self,task,validated,emit))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        result['finished']=time.time()
        return result

    async def command(self, task_id, argv, cwd, timeout, emit):
        process=await asyncio.create_subprocess_exec(*argv,cwd=cwd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        self.processes[task_id]=process
        captured={'stdout':'','stderr':''}
        async def pump(pipe,key):
            while chunk:=await pipe.read(4096):
                text=chunk.decode('utf-8',errors='replace')
                captured[key]=(captured[key]+text)[-200000:]
                await emit(key,{'text':text})
        try:
            await asyncio.wait_for(asyncio.gather(pump(process.stdout,'stdout'),pump(process.stderr,'stderr'),process.wait()),timeout)
            return {**captured,'exit_code':process.returncode,'status':'succeeded' if process.returncode==0 else 'failed'}
        except asyncio.TimeoutError:
            await asyncio.to_thread(kill_tree,process.pid)
            await process.wait()
            return {**captured,'exit_code':process.returncode,'status':'failed','error':'执行超时，已终止本次进程树'}
        except asyncio.CancelledError:
            await asyncio.to_thread(kill_tree,process.pid); await process.wait(); raise
        finally: self.processes.pop(task_id,None)

def document(root,args):
    p=inside(root,args['path']); content=args['content']; ext=p.suffix.lower()
    if content is not None:
        if p.exists(): raise ValueError('文档创建不覆盖已有文件，请使用新的输出路径')
        p.parent.mkdir(parents=True,exist_ok=True)
    if ext=='.docx':
        from docx import Document
        if content is not None:
            d=Document(); d.add_paragraph(content); d.save(p)
        output='\n'.join(x.text for x in Document(p).paragraphs)
    elif ext=='.xlsx':
        from openpyxl import Workbook,load_workbook
        if content is not None:
            w=Workbook()
            for row in json.loads(content): w.active.append(row)
            w.save(p)
        w=load_workbook(p,data_only=False); output=list(w.active.values); w.close()
    elif ext=='.pdf':
        from pypdf import PdfReader
        if content is not None:
            from reportlab.pdfgen.canvas import Canvas
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            c=Canvas(str(p)); c.setFont('STSong-Light',12); y=800
            for line in content.splitlines():
                for at in range(0,max(1,len(line)),38):
                    c.drawString(40,y,line[at:at+38]); y-=18
                    if y<50: c.showPage(); c.setFont('STSong-Light',12); y=800
            c.save()
        output='\n'.join(page.extract_text() or '' for page in PdfReader(p).pages)
        if not output.strip(): output='未提取到文字：可能为扫描 PDF，未配置 OCR。'
    elif ext in ('.txt','.md','.json','.csv'):
        if content is not None: p.write_text(content,encoding='utf-8')
        output=p.read_text(encoding='utf-8')
        if ext=='.json': json.loads(output)
    else: raise ValueError('不支持的文档格式')
    return {'output':output,'artifacts':[str(p.relative_to(Path(root).resolve()))] if content is not None else [],
            'verification':'文件重新解析成功；未进行布局渲染、公式重算或 Office 保真验证'}

async def mcp_call(args):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    if args['transport']=='stdio':
        transport=stdio_client(StdioServerParameters(command=args['command'],args=args['args']))
    elif args['transport']=='http': transport=streamablehttp_client(args['url'])
    else: raise ValueError('MCP transport 必须是 stdio 或 http')
    async with transport as streams:
        async with ClientSession(streams[0],streams[1]) as session:
            await session.initialize()
            discovered=await session.list_tools()
            if not args['tool']: return discovered.model_dump(mode='json')
            names={t.name for t in discovered.tools}
            if args['tool'] not in names: raise ValueError('MCP 工具不存在')
            result=await session.call_tool(args['tool'],args['arguments'])
            output=result.model_dump(mode='json')
    if result.isError: raise RuntimeError('MCP 服务返回工具错误')
    return output
