import json
from fastapi.testclient import TestClient
from services.agent.app import create_app
from tests.test_core import wait_state

def test_memory_history_search_export_and_delete_propagation(tmp_path):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        mid=c.put('/api/memories/new',json={'scope':'personal','content':'项目决定使用 SQLite','kind':'explicit'}).json()['id']
        assert c.get('/api/memories?q=项目决定').json()[0]['id']==mid
        c.put('/api/memories/'+mid,json={'scope':'personal','content':'迁移到 Postgres','kind':'unconfirmed'})
        assert not c.get('/api/memories?q=SQLite').json()
        history=c.get(f'/api/memories/{mid}/history').json()
        assert history[0]['snapshot']['content']=='项目决定使用 SQLite'
        exported=c.get('/api/memories/export').json()
        assert exported['memories'][0]['kind']=='unconfirmed' and len(exported['history'])==1
        assert c.delete('/api/memories/'+mid).status_code==200
        assert c.get(f'/api/memories/{mid}/history').json()==[]
        assert c.get('/api/memories/export').json()['memories']==[]
        assert app.state.store.rows('SELECT * FROM memory_fts')==[]
        assert c.put('/api/memories/new',json={'content':''}).status_code==400

def test_auto_summary_is_opt_in_after_user_acceptance_and_project_scoped(tmp_path):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        sid=c.post('/api/sessions',json={}).json()['id']
        def run():
            t=c.post(f'/api/sessions/{sid}/tasks',json={'goal':'真实摘要测试','workspace':'','mode':'workspace','deliverables':['proof.txt'],'acceptance':['检查内容'],'script':[{'name':'files.write','arguments':{'path':'proof.txt','content':'proof'}}],'checks':[{'id':'proof','label':'产物存在','kind':'file_exists','path':'proof.txt'}]}).json()
            c.post('/api/tasks/'+t['id']+'/start',json={});wait_state(c,t['id'],{'awaiting_feedback'});return t
        assert c.get('/api/memory-settings').json()=={'auto_summary':False}
        first=run();c.post('/api/tasks/'+first['id']+'/accept',json={})
        assert c.get('/api/memories').json()==[]
        c.put('/api/memory-settings',json={'auto_summary':True});task=run()
        assert c.get('/api/memories').json()==[]
        c.post('/api/tasks/'+task['id']+'/accept',json={})
        memory=c.get('/api/memories').json()[0]
        assert memory['scope']==task['spec']['workspace'] and memory['source']=='accepted_task:'+task['id']
        assert 'succeeded' in memory['content']
        assert app.state.store.search_memories(scopes=['personal'])==[]
        assert app.state.store.search_memories('摘要测试',scopes=[task['spec']['workspace']])[0]['id']==memory['id']
        c.delete('/api/memories/'+memory['id'])
        assert not app.state.store.search_memories(scopes=[task['spec']['workspace']])
        c.put('/api/memory-settings',json={'auto_summary':False});last=run();c.post('/api/tasks/'+last['id']+'/accept',json={})
        assert not c.get('/api/memories').json()

def test_skill_validation_versions_and_listing_never_execute(tmp_path):
    app=create_app(tmp_path/'data','t')
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        skill=c.get('/api/skills').json()[0];assert skill['sha256'] and skill['id']
        body={k:v for k,v in skill.items() if k not in ('id','sha256')}
        assert c.put('/api/skills/custom',json=body).status_code==200
        body['steps']=['检查现有目录，不修改文件']
        assert c.put('/api/skills/custom',json=body).status_code==200
        saved=next(s for s in c.get('/api/skills').json() if s['id']=='custom')
        assert saved['version']==2 and len(list((tmp_path/'data/skills/history').glob('custom-*.json')))==1
        assert c.put('/api/skills/bad',json={**body,'tools':['unknown.execute']}).status_code==400
        assert not c.get('/api/bootstrap').json()['tasks']
