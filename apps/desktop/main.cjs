const {app,BrowserWindow,ipcMain,dialog,Notification}=require('electron');
const fs=require('node:fs');const path=require('node:path');const {spawn}=require('node:child_process');
const root=app.isPackaged?process.resourcesPath:path.resolve(__dirname,'../..');
const base='http://127.0.0.1:8765';
const data=process.env.AGENT_DATA||(app.isPackaged?path.join(app.getPath('userData'),'data'):path.join(root,'data'));
let win;
async function healthy(){try{const r=await fetch(base+'/health');return (await r.json()).app==='local-agent'}catch{return false}}
function trusted(event){return event.sender===win?.webContents&&event.senderFrame.url.startsWith(base+'/')}
if(!app.requestSingleInstanceLock())app.quit();
else app.whenReady().then(async()=>{
 if(!await healthy()){
  const executable=app.isPackaged?path.join(root,'backend','local-agent-backend.exe'):(process.env.AGENT_PYTHON||'python');
  const args=app.isPackaged?[]:[path.join(root,'scripts','run_backend.py')];
  const child=spawn(executable,args,{cwd:root,env:{...process.env,AGENT_DATA:data,AGENT_RESOURCE_ROOT:root},detached:true,stdio:'ignore',windowsHide:true});child.on('error',e=>dialog.showErrorBox('后端启动失败',e.message));child.unref();
  for(let i=0;i<60&&!await healthy();i++)await new Promise(r=>setTimeout(r,500));
 }
 if(!await healthy()){dialog.showErrorBox('后端未启动','请运行 scripts/start-web.ps1 检查后端依赖和端口 8765。');app.quit();return}
 if(!fs.existsSync(path.join(data,'client.token'))){dialog.showErrorBox('无法认证','共享后端的 AGENT_DATA 与桌面不一致。');app.quit();return}
 win=new BrowserWindow({width:1440,height:950,minWidth:850,minHeight:650,title:'本地 Agent 工作台',backgroundColor:'#fafbf8',webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.webContents.on('will-navigate',(event,url)=>{if(new URL(url).origin!==base)event.preventDefault()});
 win.webContents.session.setPermissionRequestHandler((contents,permission,callback)=>callback(false));
 ipcMain.handle('directory',async event=>{if(!trusted(event))throw Error('Unauthorized IPC');const r=await dialog.showOpenDialog(win,{properties:['openDirectory']});return r.canceled?null:r.filePaths[0]});
 ipcMain.handle('notify',async(event,title)=>{if(!trusted(event)||typeof title!=='string')throw Error('Unauthorized IPC');new Notification({title:'本地 Agent',body:title.slice(0,200)}).show()});
 await win.loadURL(base+'/#token='+encodeURIComponent(fs.readFileSync(path.join(data,'client.token'),'utf8').trim()));
});
app.on('window-all-closed',()=>app.quit()); // Shared backend intentionally remains alive; see user guide.
