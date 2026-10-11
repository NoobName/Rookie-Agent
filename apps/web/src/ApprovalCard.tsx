import React,{useState} from 'react';

export function ApprovalCard({call,decide}:{call:any;decide:(body:any)=>void}){
 const [scope,setScope]=useState('once'),[hours,setHours]=useState(1);
 return <section className="approval"><h3>需要你的授权：{call.tool}</h3><pre>{JSON.stringify(call.args,null,2)}</pre>{['terminal.run','mcp.call','checks.run','git.commit'].includes(call.tool)&&<p>命令与外部工具可以访问工作区外的资源，请核对完整参数。</p>}<label>批准范围<select value={scope} onChange={e=>setScope(e.target.value)}><option value="once">仅这一次</option><option value="task">本任务中参数完全相同的操作</option><option value="workspace">此工作区中参数完全相同的操作</option></select></label>{scope!=='once'&&<label>有效小时数（最多 168）<input type="number" min="0.01" max="168" step="any" value={hours} onChange={e=>setHours(Number(e.target.value))}/></label>}<p className="muted">长期规则可在“模型与设置”撤销。参数改变后需要重新授权。</p><button className="primary" onClick={()=>decide({allow:true,scope,hours})}>批准这次操作</button> <button onClick={()=>decide({allow:false})}>拒绝</button></section>
}
