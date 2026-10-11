"""Bounded, serial, advisory-only collaboration. Submodels receive NO tools."""
import json
from .models import Strict
from pydantic import Field

class Assignment(Strict):
    role: str
    provider: str
    objective: str
    acceptance: list[str]

class CollaborationPlan(Strict):
    assignments: list[Assignment] = Field(max_length=3)

async def collaborate(main,provider_factory,messages,mappings,emit,record_usage):
    if not mappings:raise ValueError('协作需要用户配置角色 → 模型映射，不能按模型名推断')
    prompt='请为任务安排最多 3 个只读咨询子任务。仅返回 JSON {"assignments":[{"role":"角色","provider":"已授权模型 ID","objective":"目标","acceptance":["验收条件"]}]}。可用映射：'+json.dumps(mappings,ensure_ascii=False)
    async def quiet(text):pass
    plan_reply=await main.reply(messages+[{'role':'user','content':prompt}],[],quiet)
    await record_usage(main,plan_reply,messages)
    plan=CollaborationPlan.model_validate_json(plan_reply.text)
    results=[]
    for assignment in plan.assignments:
        if mappings.get(assignment.role)!=assignment.provider:raise PermissionError('主模型分派超出用户配置映射')
        provider=provider_factory(assignment.provider)
        await emit('delegation',{'role':assignment.role,'provider':assignment.provider,'objective':assignment.objective,'basis':'用户明确映射；不是能力排名'})
        submessages=[{'role':'system','content':'你是只读咨询子模型。不能执行工具、修改文件、递归委派或授予权限。输出建议及需要主执行器验证的内容。'}, {'role':'user','content':assignment.model_dump_json()}]
        reply=await provider.reply(submessages,[],quiet)
        await record_usage(provider,reply,submessages)
        results.append({'assignment':assignment.model_dump(),'output':reply.text,'verification':'未验证建议，主执行器必须使用真实工具验证'})
    return results
