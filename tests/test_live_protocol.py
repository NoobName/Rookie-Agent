import asyncio,threading,socket
import pytest,uvicorn
from services.agent.providers import OpenAICompatible
from services.agent.models import ProviderConfig
from examples.mock_api import app

async def test_actual_http_protocol_tools_and_failures():
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.listen()
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        await asyncio.sleep(.02)
    async def emit(text):pass
    try:
        config=ProviderConfig(id='mock',name='mock',model='scripted',base_url=f'http://127.0.0.1:{port}/v1',tools=True)
        reply=await OpenAICompatible(config).reply([], [{'type':'function','function':{'name':'files__list','parameters':{'type':'object'}}}],emit)
        assert reply.calls[0]['name']=='files__list' and reply.usage['prompt_tokens']==11
        import httpx
        with pytest.raises(httpx.HTTPStatusError):await OpenAICompatible(config.model_copy(update={'model':'rate-limit'})).reply([],[],emit)
        with pytest.raises(ValueError):await OpenAICompatible(config.model_copy(update={'model':'truncated'})).reply([],[],emit)
    finally:server.should_exit=True;await asyncio.to_thread(thread.join,5);sock.close()
