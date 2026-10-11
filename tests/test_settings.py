import json,time
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from services.agent.app import create_app
from services.agent.models import ProviderConfig
from services.agent.providers import OpenAICompatible
from tests.test_core import wait_state

@pytest.fixture
def vault(monkeypatch):
    import keyring
    values={}
    backend=type('FakeWindows',(),{'__module__':'keyring.backends.Windows'})()
    monkeypatch.setattr(keyring,'get_keyring',lambda:backend)
    monkeypatch.setattr(keyring,'set_password',lambda service,ref,secret:values.__setitem__(ref,secret))
    monkeypatch.setattr(keyring,'get_password',lambda service,ref:values.get(ref))
    monkeypatch.setattr(keyring,'delete_password',lambda service,ref:values.pop(ref,None))
    return values

def test_credentials_survive_stale_save_and_delete_cleans_vault(tmp_path,vault):
    with TestClient(create_app(tmp_path/'data','t'),headers={'Authorization':'Bearer t'}) as c:
        config=ProviderConfig(id='p',name='test',model='fixture').model_dump()
        assert c.put('/api/providers/p',json=config).status_code==200
        assert c.post('/api/providers/p/credential',json={'secret':'sensitive-fixture'}).status_code==200
        assert c.get('/api/providers/p/credential').json()['saved']
        assert c.put('/api/providers/p',json={**config,'name':'renamed','credential_ref':'forged'}).status_code==200
        p=next(p for p in c.get('/api/bootstrap').json()['providers'] if p['id']=='p')
        assert p['credential_ref'] in vault and p['credential_ref']!='forged'
        assert 'sensitive-fixture' not in c.get('/api/bootstrap').text
        assert c.get('/api/providers/p/credential').json()['saved']
        assert c.delete('/api/providers/p').status_code==200 and not vault
        assert [p['id'] for p in c.get('/api/bootstrap').json()['providers']]==['scripted']
        assert c.delete('/api/providers/scripted').status_code==400

def test_empty_model_rejected_and_http_errors_are_actionable_without_secret(tmp_path,vault):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        assert c.put('/api/providers/p',json={'id':'p','name':'test','model':'  '}).status_code==400
        config=ProviderConfig(id='p',name='test',model='fixture',streaming=False)
        c.put('/api/providers/p',json=config.model_dump())
        for status in (400,401,402,403,404,422,429,500):
            transport=httpx.MockTransport(lambda req:httpx.Response(status,json={'error':{'message':'secret-fixture echoed by remote'}}))
            app.state.engine.provider=lambda _:OpenAICompatible(config,transport)
            result=c.post('/api/providers/p/test',json={}).json()
            assert not result['ok'] and f'HTTP {status}' in result['detail']
            assert 'secret-fixture' not in json.dumps(result)
        sid=c.post('/api/sessions',json={}).json()['id']
        result=c.post(f'/api/sessions/{sid}/chat',json={'provider':'p','content':'hello'})
        assert result.status_code==502 and 'HTTP 500' in result.text and 'secret-fixture' not in result.text

def test_delete_session_removes_records_preserves_artifacts_and_blocks_active(tmp_path):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        sid=c.post('/api/sessions',json={'title':'delete me'}).json()['id']
        task=c.post(f'/api/sessions/{sid}/tasks',json={'goal':'demo','workspace':'','deliverables':['file'],'acceptance':['review'],'mode':'workspace'}).json();tid=task['id']
        c.post(f'/api/tasks/{tid}/start',json={});wait_state(c,tid,{'awaiting_approval'})
        assert c.delete('/api/sessions/'+sid).status_code==400
        assert Path(task['spec']['workspace'],'hello_agent.py').is_file()
        c.post(f'/api/tasks/{tid}/pause',json={})
        c.post(f'/api/sessions/{sid}/chat',json={'provider':'scripted','content':'hello'})
        app.state.store.run('INSERT INTO schedules VALUES(?,?,?,?)',('sched',json.dumps({'session_id':sid}),time.time()+100,0))
        assert c.delete('/api/sessions/'+sid).status_code==200
        assert not c.get('/api/bootstrap').json()['sessions'] and not c.get('/api/bootstrap').json()['tasks']
        for table in ('messages','calls','events','call_meta','task_runtime','grants','schedules'):
            assert not app.state.store.rows('SELECT * FROM '+table)
        assert Path(task['spec']['workspace'],'hello_agent.py').is_file()

def test_provider_deletion_blocks_active_task(tmp_path,vault):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        c.put('/api/providers/p',json={'id':'p','name':'test','model':'fixture'})
        sid=c.post('/api/sessions',json={}).json()['id']
        task=c.post(f'/api/sessions/{sid}/tasks',json={'goal':'wait','workspace':'','deliverables':['a'],'acceptance':['b']}).json();tid=task['id']
        # Use the real scripted execution to enter authorization, then register dependency.
        c.post(f'/api/tasks/{tid}/start',json={});wait_state(c,tid,{'awaiting_approval'})
        spec=task['spec'];spec['collaboration_mapping']={'reviewer':'p'}
        app.state.store.run('UPDATE tasks SET spec=? WHERE id=?',(json.dumps(spec),tid))
        assert c.delete('/api/providers/p').status_code==400
        c.post(f'/api/tasks/{tid}/pause',json={})
        assert c.delete('/api/providers/p').status_code==200

async def test_model_discovery_works_before_model_selected(vault):
    vault['own-ref']='local-test-secret';seen=[]
    def handler(req):
        seen.append((str(req.url),req.headers.get('Authorization')))
        return httpx.Response(200,json={'data':[{'id':'available-model'},{'id':'available-model'}]})
    provider=OpenAICompatible(ProviderConfig(id='p',name='p',model='',credential_ref='own-ref',base_url='https://models.test/v1'),httpx.MockTransport(handler))
    assert await provider.list_models()==['available-model']
    assert seen==[('https://models.test/v1/models','Bearer local-test-secret')]
