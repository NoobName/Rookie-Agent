import React,{useState} from 'react';
import type {Task,TaskSpec,AcceptanceCheck} from '../../../packages/contracts';

export function CheckEditor({spec,onChange}:{spec:TaskSpec;onChange:(s:TaskSpec)=>void}){
 const checks=spec.checks||[];
 const update=(i:number,change:Partial<AcceptanceCheck>)=>onChange({...spec,checks:checks.map((c,n)=>n===i?{...c,...change}:c)});
 return <section><h2>实际验收检查</h2><p className="muted">执行器按这些条件检查真实产物。命令检查也需要授权；上方文字条件仍由你最终验收。</p>{checks.map((c,i)=><div className="result" key={c.id}>
 <label>检查名称<input value={c.label} onChange={e=>update(i,{label:e.target.value})}/></label>
 <label>检查方式<select value={c.kind} onChange={e=>update(i,{kind:e.target.value as AcceptanceCheck['kind']})}><option value="file_exists">文件存在</option><option value="text_contains">文本包含指定内容</option><option value="command">命令退出码为 0</option><option value="manual">人工确认</option></select></label>
 {['file_exists','text_contains'].includes(c.kind)&&<label>检查文件路径<input value={c.path||''} onChange={e=>update(i,{path:e.target.value})}/></label>}
 {c.kind==='text_contains'&&<label>必须包含的文本<textarea value={c.contains||''} onChange={e=>update(i,{contains:e.target.value})}/></label>}
 {c.kind==='command'&&<><label>程序与参数（每行一个，不加引号）<textarea value={(c.argv||[]).join('\n')} onChange={e=>update(i,{argv:e.target.value.split('\n')})}/></label><label>超时秒数<input type="number" min="1" max="600" value={c.timeout||60} onChange={e=>update(i,{timeout:Number(e.target.value)})}/></label></>}
 <button onClick={()=>onChange({...spec,checks:checks.filter((_,n)=>n!==i)})}>移除检查</button></div>)}
 <button onClick={()=>onChange({...spec,checks:[...checks,{id:'check_'+crypto.randomUUID().replaceAll('-',''),label:'检查交付文件',kind:'file_exists',path:''}]})}>＋ 添加验收检查</button>
 <details><summary>执行保护设置</summary>{[['max_steps','最多模型轮次',40,1,200],['repair_rounds','验收失败后最多修复轮次',3,0,10],['provider_retries','网络暂时失败重试次数',2,0,5]].map(([key,label,fallback,min,max])=><label key={key}>{label}<input type="number" min={min} max={max} value={spec.guardrails?.[key]??fallback} onChange={e=>onChange({...spec,guardrails:{...spec.guardrails,[key]:Number(e.target.value)}})}/></label>)}</details></section>
}

export function VerificationReport({task}:{task:Task}){
 const v=task.verification;if(!v)return null;
 const status:Record<string,string>={succeeded:'通过',failed:'失败',manual_required:'待人工确认'};
 return <section className="result"><h3>实际验收报告</h3>{v.checks.length?v.checks.map(c=><p key={c.id}>{c.label}：{status[c.status]||c.status}</p>):<p>尚未配置机器检查，没有自动通过的结论。</p>}{v.unresolved_calls.length>0&&<p className="error">仍有 {v.unresolved_calls.length} 项未解决的执行失败。</p>}<p>以下文字条件请对照产物确认：</p><ul>{v.manual_acceptance.map((s,i)=><li key={i}>{s}</li>)}</ul></section>
}

export function RecoveryCard({call,onDecision}:{call:any;onDecision:(decision:string,note:string)=>void}){
 const [note,setNote]=useState('');
 return <section className="approval"><h3>审查中断操作：{call.tool}</h3><p>操作可能已经产生副作用。先检查实际文件或外部状态，再选择后续处理。跳过不会将此调用标记为成功；重试仍受工具授权控制。</p><pre>{JSON.stringify(call.args,null,2)}</pre><label>审查说明<input value={note} onChange={e=>setNote(e.target.value)} placeholder="描述已检查的实际状态"/></label><button disabled={!note.trim()} onClick={()=>onDecision('skip',note)}>已审查，跳过此步骤</button> <button disabled={!note.trim()} onClick={()=>onDecision('retry',note)}>已审查，允许重新尝试</button></section>
}
