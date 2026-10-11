import React,{useEffect,useState} from 'react';
const fresh=()=>({id:'',name:'我的模型',base_url:'https://api.openai.com/v1',model:'',tools:false,vision:false,streaming:true,timeout:60,extra:{}});
export function Settings({providers,act,request}:{providers:any[];act:(fn:()=>Promise<any>)=>Promise<void>;request:(path:string,method?:string,body?:unknown)=>Promise<any>}){
 const [config,setConfig]=useState<any>(()=>providers.find(p=>p.id!=='scripted')||fresh()),[secret,setSecret]=useState(''),[result,setResult]=useState(''),[grants,setGrants]=useState<any[]>([]),[dirty,setDirty]=useState(false),[credential,setCredential]=useState({saved:false,detail:'尚未保存密钥'});
 const existing=providers.some(p=>p.id===config.id&&p.id!=='scripted');
 const [models,setModels]=useState<string[]>([]);
 useEffect(()=>{setModels([])},[config.id,config.base_url]);
 const change=(value:any)=>{setConfig(value);setDirty(true);setResult('')};
 useEffect(()=>{request('/grants').then(setGrants).catch(()=>{})},[]);
 useEffect(()=>{let live=true;setCredential({saved:false,detail:'正在检查密钥保存状态…'});if(existing)request(`/providers/${config.id}/credential`).then(r=>{if(live)setCredential(r)}).catch(()=>{if(live)setCredential({saved:false,detail:'无法读取密钥状态'})});else setCredential({saved:false,detail:'尚未保存密钥'});return()=>{live=false}},[config.id,existing]);
 async function save(){
  if(!config.id.trim()||!config.model.trim())throw new Error('请填写配置 ID 和模型 ID；显示名称不能代替模型 ID');
  await request('/providers/'+config.id,'PUT',config);
  if(secret.trim()){await request(`/providers/${config.id}/credential`,'POST',{secret:secret.trim()});setSecret('')}
  const b=await request('/bootstrap');setConfig(b.providers.find((p:any)=>p.id===config.id));setCredential(await request(`/providers/${config.id}/credential`));setDirty(false);setResult('配置已保存。密钥框清空是为了避免回显；留空再次保存会保留已有密钥。');
 }
 async function probe(mode='chat'){
  if(dirty||secret)throw new Error('配置或密钥已修改，请先保存再测试');
  const r=await request(`/providers/${config.id}/test`,'POST',{mode});setResult((r.ok?'测试通过：':'测试失败：')+(r.detail||r.error||'')+(r.ok&&r.text?'\n'+r.text:''));
  const b=await request('/bootstrap');setConfig(b.providers.find((p:any)=>p.id===config.id)||fresh());
 }
 return <div className="content"><h1>连接你选择的模型</h1><p className="muted">配置 ID 用于本地管理；模型 ID 必须填写服务商提供的准确名称。</p>
 <div className="tabs">{providers.filter(p=>p.id!=='scripted').map(p=><button key={p.id} onClick={()=>{setConfig(p);setSecret('');setDirty(false);setResult('')}}>{p.name}</button>)}<button onClick={()=>{setConfig(fresh());setSecret('');setDirty(true);setResult('')}}>＋ 新建模型配置</button></div>
 {[['id','配置 ID'],['name','显示名称'],['base_url','API Base URL（包含 /v1 等实际前缀）'],['model','模型 ID']].map(([k,title])=><label key={k}>{title}<input list={k==='model'?'provider-model-list':undefined} value={config[k]||''} onChange={e=>change({...config,[k]:e.target.value})}/></label>)}
 <datalist id="provider-model-list">{models.map(id=><option key={id} value={id}/>)}</datalist>
 <button disabled={!existing||dirty||!!secret} onClick={()=>act(async()=>{const r=await request(`/providers/${config.id}/models`);setModels(r.models);setResult(r.models.length?'已读取服务商模型列表，请在模型 ID 输入框选择，保存后再测试。':'服务商未返回可用模型。')})}>获取已保存配置的模型列表</button>
 {models.length>0&&<div className="tabs">{models.map(id=><button key={id} onClick={()=>change({...config,model:id})}>{id}</button>)}</div>}
 {!config.model.trim()&&<p className="error">模型 ID 不能为空。请从服务商控制台或模型列表复制，不能只填写显示名称。</p>}
 <div className="two">{[['input_price','每百万输入 token 单价'],['output_price','每百万输出 token 单价']].map(([k,l])=><label key={k}>{l}<input type="number" min="0" step="any" value={config[k]??''} onChange={e=>change({...config,[k]:e.target.value===''?null:Number(e.target.value)})}/></label>)}</div>
 <label>超时（秒）<input type="number" min="1" max="600" value={config.timeout} onChange={e=>change({...config,timeout:Number(e.target.value)})}/></label>
 <label>API 密钥（只保存到 Windows 凭据存储）<input type="password" autoComplete="off" value={secret} placeholder={credential.saved?'已保存；留空保留，输入新密钥替换':'输入 API 密钥'} onChange={e=>setSecret(e.target.value)}/></label><p role="status">{credential.detail}</p>
 <div className="checks">{[['tools','原生工具调用'],['streaming','流式响应'],['vision','视觉能力（实际能力待测试）']].map(([k,l])=><label key={k}><input type="checkbox" checked={config[k]} onChange={e=>change({...config,[k]:e.target.checked})}/>{l}</label>)}</div>
 <button className="primary" disabled={!config.id.trim()||!config.model.trim()} onClick={()=>act(save)}>保存配置</button> <button disabled={!existing||dirty||!!secret} onClick={()=>act(()=>probe())}>连接测试</button>
 {existing&&<button className="danger" onClick={()=>{if(window.confirm('删除此模型配置及其保存的密钥？历史记录保留；继续旧任务前需要重新选择模型。'))act(async()=>{await request('/providers/'+config.id,'DELETE');setConfig(fresh());setSecret('');setDirty(true);setResult('模型配置及密钥已删除')})}}>删除模型配置</button>}
 {(dirty||!!secret)&&<p className="muted">有尚未保存的修改，请保存后测试。</p>}
 <div className="tabs">{[['chat','普通聊天'],['stream','流式'],['tools','工具协议'],['vision','视觉样本']].map(([mode,label])=><button key={mode} disabled={!existing||dirty||!!secret} onClick={()=>act(()=>probe(mode))}>{label}测试</button>)}</div>
 {result&&<p className="notice" role="status" style={{whiteSpace:'pre-wrap'}}>{result}</p>}<pre>{JSON.stringify(config.verified||{},null,2)}</pre>
 <h2>授权记录</h2>{grants.map(g=><div className="row" key={g.id}><span>{g.tool} · {g.scope} · {g.revoked?'已撤销 / 已消费':g.expires*1000<Date.now()?'已过期':'有效'} · {new Date(g.expires*1000).toLocaleString()}{g.arguments&&<details><summary>具体规则</summary><pre>{g.workspace}{'\n'}{g.arguments}</pre></details>}</span>{!g.revoked&&<button onClick={()=>act(async()=>{await request('/grants/'+g.id,'DELETE');setGrants(await request('/grants'))})}>撤销</button>}</div>)}
 </div>
}
