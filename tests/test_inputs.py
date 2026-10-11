import io,json,time
import pytest
from fastapi.testclient import TestClient
from services.agent.app import create_app
from services.agent.attachments import context_parts
from services.agent.integrations import send_email
from services.agent.store import Store,dump

def test_attachment_parse_and_vision_gate(tmp_path):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as client:
        response=client.post('/api/attachments',files={'file':('资料.txt','真实附件内容'.encode(),'text/plain')})
        ident=response.json()['id']
        assert '真实附件内容' in context_parts(app.state.store,[ident])[0]['text']
        from PIL import Image
        buf=io.BytesIO();Image.new('RGB',(8,8),'red').save(buf,format='PNG')
        ident=client.post('/api/attachments',files={'file':('shot.png',buf.getvalue(),'image/png')}).json()['id']
        with pytest.raises(ValueError,match='视觉'):context_parts(app.state.store,[ident],False)
        assert context_parts(app.state.store,[ident],True)[0]['image_url']['url'].startswith('data:image/png;base64,')
        with pytest.raises(ValueError):context_parts(app.state.store,['../../client.token'],True)

def test_email_disabled_and_recording_transport(tmp_path):
    store=Store(tmp_path/'db');args={'to':['receiver@example.test'],'subject':'Reminder','body':'Completed'}
    with pytest.raises(PermissionError):send_email(store,args)
    store.run('INSERT INTO settings VALUES(?,?)',('email',dump({'enabled':True,'sender':'sender@example.test'})))
    inbox=[];result=send_email(store,args,inbox.append)
    assert result['test_only'] and inbox[0]['To']=='receiver@example.test'
    assert 'Completed' in inbox[0].get_content()

def test_custom_workflow_mcp_approval(tmp_path):
    import sys
    from pathlib import Path
    from tests.test_core import wait_state
    root=Path(__file__).resolve().parents[1]
    with TestClient(create_app(tmp_path/'data','t'),headers={'Authorization':'Bearer t'}) as c:
        sid=c.post('/api/sessions',json={}).json()['id']
        spec={'goal':'Discover MCP','workspace':'','provider':'scripted','tools':['mcp.call'],'deliverables':['tools'],'acceptance':['actual list'],
              'script':[{'name':'mcp.call','arguments':{'command':sys.executable,'args':[str(root/'examples/mcp_server.py')]}}]}
        tid=c.post(f'/api/sessions/{sid}/tasks',json=spec).json()['id'];c.post(f'/api/tasks/{tid}/start',json={})
        wait_state(c,tid,{'awaiting_approval'});call=c.get(f'/api/tasks/{tid}/calls').json()[0]
        c.post('/api/approvals/'+call['id'],json={'allow':True});wait_state(c,tid,{'awaiting_feedback'})
        output=c.get(f'/api/tasks/{tid}/calls').json()[0]['result']['output']
        assert any(t['name']=='add' for t in output['tools'])

async def test_revert_never_overwrites_subsequent_edits(tmp_path):
    from services.agent.tools import Tools
    import hashlib
    workspace=tmp_path/'w';workspace.mkdir();store=Store(tmp_path/'data');tools=Tools(store)
    task={'id':'t','spec':{'workspace':str(workspace)}}
    async def emit(*args):pass
    result=await tools.execute(task,'files.write',{'path':'a.txt','content':'first\r\n'},emit)
    change=result['change_id'];(workspace/'a.txt').write_text('user edits')
    result=await tools.execute(task,'files.revert',{'change_id':change},emit)
    assert result['status']=='failed' and (workspace/'a.txt').read_text()=='user edits'
    result=await tools.execute(task,'files.write',{'path':'b.txt','content':'new file'},emit)
    result=await tools.execute(task,'files.revert',{'change_id':result['change_id']},emit)
    assert result['status']=='succeeded' and not (workspace/'b.txt').exists()
    (workspace/'original.txt').write_bytes(b'original\r\n')
    result=await tools.execute(task,'files.write',{'path':'original.txt','content':'changed','expected_sha256':hashlib.sha256(b'original\r\n').hexdigest()},emit)
    await tools.execute(task,'files.revert',{'change_id':result['change_id']},emit)
    assert (workspace/'original.txt').read_bytes()==b'original\r\n'
