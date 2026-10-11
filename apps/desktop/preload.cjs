const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('desktop',{pickDirectory:()=>ipcRenderer.invoke('directory'),notify:title=>ipcRenderer.invoke('notify',title)});
