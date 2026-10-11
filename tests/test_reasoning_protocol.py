import json
import httpx
import pytest
from fastapi.testclient import TestClient
from services.agent.app import create_app
from services.agent.engine import Engine
from services.agent.models import ProviderConfig
from services.agent.providers import OpenAICompatible
from tests.test_execution import create
from tests.test_core import wait_state


@pytest.mark.parametrize('streaming',[False,True])
def test_reasoning_tool_batches_survive_roundtrip_and_reload(tmp_path,streaming):
    requests=[]
    first={'role':'assistant','content':'Checking files','reasoning_content':'protocol fixture thought',
           'tool_calls':[{'id':f'remote_{i}','type':'function','function':{'name':'files__list','arguments':'{}'}} for i in range(2)]}
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)>1:
            messages=body['messages'];assistant=next(m for m in messages if m['role']=='assistant')
            assert assistant==first
            assert [m['tool_call_id'] for m in messages if m['role']=='tool']==['remote_0','remote_1']
            msg={'role':'assistant','content':'Done','reasoning_content':'finished'}
        else:msg=first
        if not streaming:return httpx.Response(200,json={'choices':[{'message':msg}]})
        deltas=[{'reasoning_content':msg['reasoning_content'][:8]},{'reasoning_content':msg['reasoning_content'][8:]},{'content':msg['content']}]
        for i,call in enumerate(msg.get('tool_calls',[])):
            deltas.extend([{'tool_calls':[{'index':i,'id':call['id'],'function':{'name':call['function']['name'],'arguments':'{'}}]},
                           {'tool_calls':[{'index':i,'function':{'arguments':'}'}}]}])
        content=''.join('data: '+json.dumps({'choices':[{'delta':d}]})+'\n\n' for d in deltas)+'data: [DONE]\n\n'
        return httpx.Response(200,text=content)
    app=create_app(tmp_path/'data','t')
    config=ProviderConfig(id='fixture',name='fixture',model='fixture',base_url='https://fixture.invalid',tools=True,streaming=streaming)
    app.state.engine.provider=lambda _:OpenAICompatible(config,transport=httpx.MockTransport(handler))
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        task=create(c,tools=['files.list']);tid=task['id']
        c.post(f'/api/tasks/{tid}/start',json={})
        assert wait_state(c,tid,{'awaiting_feedback','failed'})['state']=='awaiting_feedback'
        store=app.state.engine.store
        assert len(requests)==2
        rebuilt=Engine(store).messages([],tid,120000,'scripted')
        assert rebuilt[0]==first
        # Missing one result must not replay a malformed partial batch.
        row=store.one('SELECT id FROM calls WHERE task_id=? LIMIT 1',(tid,))
        store.run("UPDATE calls SET status='not_executed' WHERE id=?",(row['id'],))
        assert all(m['role']=='user' for m in Engine(store).messages([],tid,120000,'scripted'))
        # Old task records lacking protocol metadata are evidence, not invented assistant messages.
        store.run('DELETE FROM call_turns')
        assert all(m['role']=='user' for m in Engine(store).messages([],tid,120000,'scripted'))
        assert c.delete('/api/sessions/'+task['session_id']).status_code==200
        assert not store.rows('SELECT * FROM model_turns')


def test_http_error_does_not_expose_url_or_remote_body(tmp_path):
    app=create_app(tmp_path/'data','t')
    config=ProviderConfig(id='fixture',name='fixture',model='fixture',base_url='https://fixture.invalid/private',tools=True)
    app.state.engine.provider=lambda _:OpenAICompatible(config,transport=httpx.MockTransport(lambda r:httpx.Response(400,json={'error':'secret-echo'})))
    with TestClient(app,headers={'Authorization':'Bearer t'}) as c:
        task=create(c,tools=['files.list']);tid=task['id'];c.post(f'/api/tasks/{tid}/start',json={})
        assert wait_state(c,tid,{'failed'})['state']=='failed'
        events=json.dumps(app.state.engine.store.rows('SELECT payload FROM events WHERE task_id=?',(tid,)),ensure_ascii=False)
        assert 'HTTP 400' in events
        assert 'fixture.invalid' not in events and 'secret-echo' not in events
