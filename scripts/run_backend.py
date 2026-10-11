"""Single loopback service. Python dependencies may live in .runtime/python."""
import os, sys, site
from pathlib import Path
root=Path(os.getenv('AGENT_RESOURCE_ROOT',Path(__file__).resolve().parents[1]))
sys.path[:0]=[str(root),str(root/'.runtime/python')]
site.addsitedir(str(root/'.runtime/python'))
os.chdir(root)
if __name__=='__main__':
    import uvicorn
    import socket
    from services.agent.app import create_app
    port=int(os.getenv('AGENT_PORT','8765'))
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    try:listener.bind(('127.0.0.1',port))
    except OSError:
        listener.close();raise SystemExit(f'端口 {port} 已被占用；未打开数据库或中断现有任务。')
    listener.listen(128)
    try:
        app=create_app()
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False))
        app.state.shutdown=lambda:setattr(server,'should_exit',True)
        server.run(sockets=[listener])
    finally:listener.close()
