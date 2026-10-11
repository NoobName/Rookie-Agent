"""CMD-friendly, standard-library launcher. Never kills a process by port or PID."""
import argparse, json, os, subprocess, sys, time, urllib.error, urllib.request, webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('AGENT_DATA',str(ROOT/'data'))).resolve()
PORT=int(os.getenv('AGENT_PORT','8765'))
URL=f'http://127.0.0.1:{PORT}'

def request(path,auth=False,method='GET'):
    headers={}
    if auth:headers['Authorization']='Bearer '+(DATA/'client.token').read_text('utf-8').strip()
    req=urllib.request.Request(URL+path,headers=headers,method=method)
    # Local control must not be routed through a configured external proxy.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req,timeout=2) as response:return json.load(response)

def health():
    try:return request('/health')
    except (OSError,ValueError):return None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','status','stop']);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    current=health()
    if current and current.get('app')!='local-agent':raise RuntimeError('Port is occupied by another service; nothing was stopped.')
    if args.action=='start':
        if not (ROOT/'dist/web/index.html').exists():raise RuntimeError('Build the web UI first: build.cmd')
        if not current:
            DATA.mkdir(parents=True,exist_ok=True)
            options={'cwd':ROOT,'stdin':subprocess.DEVNULL}
            if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP
            else:options['start_new_session']=True
            with (DATA/'backend.log').open('ab') as out,(DATA/'backend-error.log').open('ab') as err:
                child=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_backend.py')],stdout=out,stderr=err,**options)
            for _ in range(100):
                if child.poll() is not None:raise RuntimeError(f'Backend exited. See {DATA / "backend-error.log"}')
                current=health()
                if current:break
                time.sleep(.2)
            if not current:raise RuntimeError(f'Backend did not become ready. See {DATA / "backend-error.log"}')
        request('/api/bootstrap',auth=True) # Proves this data directory owns the service token.
        if not args.no_browser:webbrowser.open(URL+'/#token='+(DATA/'client.token').read_text('utf-8').strip())
        print(f'Agent {current["version"]} ready: {URL}')
        print('Closing the browser keeps the backend running. Use stop.cmd to stop it.')
    elif args.action=='status':
        if not current:print('Backend is not running.');return
        state=request('/api/bootstrap',auth=True)
        print(f'Agent {current["version"]}: {URL}; tasks: {len(state["tasks"])}')
    else:
        if not current:print('Backend is already stopped.');return
        request('/api/shutdown',auth=True,method='POST')
        for _ in range(100):
            if not health():print('Backend stopped.');return
            time.sleep(.1)
        raise RuntimeError('Shutdown requested but not completed; inspect the backend log.')

if __name__=='__main__':
    try:main()
    except urllib.error.HTTPError as exc:
        try:detail=json.load(exc).get('detail',str(exc))
        except Exception:detail=str(exc)
        print('ERROR:',detail,file=sys.stderr);raise SystemExit(1)
    except Exception as exc:
        print('ERROR:',str(exc),file=sys.stderr);raise SystemExit(1)
