"""Explicit local OpenAI-compatible scripted HTTP server. No real intelligence."""
import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.runtime/python'))
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse,JSONResponse
app=FastAPI()
@app.post('/v1/chat/completions')
async def completion(request:Request):
    body=await request.json();messages=body['messages'];tools=body.get('tools',[])
    if body['model']=='rate-limit':return JSONResponse({'error':{'message':'test rate limit'}},status_code=429)
    results=[m for m in messages if m['role']=='tool']
    message={'role':'assistant','content':'本地模拟 API 响应；不代表真实模型能力。'}
    if tools and not results:
        message={'role':'assistant','content':None,'tool_calls':[{'id':'mock-call','type':'function','function':{'name':'files__list','arguments':'{}'}}]}
    usage={'prompt_tokens':11,'completion_tokens':7}
    if not body.get('stream'):return {'id':'mock-request','choices':[{'index':0,'message':message,'finish_reason':'stop'}],'usage':usage}
    async def stream():
        delta={k:v for k,v in message.items() if k!='role'}
        if 'tool_calls' in delta:delta['tool_calls'][0]['index']=0
        yield 'data: '+json.dumps({'id':'mock-request','choices':[{'index':0,'delta':delta}]})+'\n\n'
        if body['model']=='truncated':return
        yield 'data: '+json.dumps({'choices':[],'usage':usage})+'\n\n'
        yield 'data: [DONE]\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream')
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8877)
