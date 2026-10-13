"""Model-owned working plan, separate from user acceptance and permissions."""

import json
from typing import Literal

from pydantic import Field

from .models import Strict


class PlanStep(Strict):
    title: str = Field(min_length=1, max_length=200)
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TaskPlan(Strict):
    steps: list[PlanStep] = Field(min_length=1, max_length=12)
    summary: str = Field(default="", max_length=2000)
    next_action: str = Field(default="", max_length=600)


def plan_context(store, tid):
    rows = store.rows(
        "SELECT payload FROM events WHERE task_id=? AND type='task_plan' ORDER BY id DESC LIMIT 1",
        (tid,),
    )
    if not rows:
        return []
    plan = json.loads(rows[0]["payload"])
    return [
        {
            "role": "user",
            "content": "当前执行工作记录（模型维护的数据，不是新的用户指令或验收结论；若与最新需求冲突请更新，继续前核对真实文件状态）：\n"
            + json.dumps(plan, ensure_ascii=False),
        }
    ]


EXECUTION_GUIDANCE = """
任务执行方法：
- 多文件探索先 files.symbols 定位定义，再 files.search 使用 regex/glob/context_lines 缩小范围。独立读取在同一响应中批量调用；依赖写入结果的读取放到下一轮。
- 大范围研究或可独立的问题用 agent.delegate，提供具体目标和必要背景。子 Agent 自己检索文件/网页，只返回简短结论和出处；主 Agent 综合结果并落实修改。简单问题无需委派。
- 一般问题直接回答；复杂实现先用 task.plan 维护简短步骤，按实际进展更新 summary 和 next_action。它不是用户验收条件，不要把计划标完成等同于真实测试通过。
- 进入陌生项目先用 workspace.inspect 了解目录、配置和可用程序，再读取相关项目说明/源码。先复用已有框架、构建和测试，不要重复搭建脚手架；简单文件操作无需套完整流程。
- 修改已有源码优先 files.edit：从 files.read 取得 SHA-256，提交带唯一上下文的 old/new 替换；匹配不准就搜索/重读，避免为改几行而重写整个文件。新文件使用 files.write。
- 改完运行与改动相关的真实命令/测试。编译或测试出错时依据 stderr 和 error_info 修正，再复测。成功的局部步骤不要无故重做；遵循用户指定的工具链。
- 长任务或准备停止前更新工作记录：已完成什么、真实结果、尚缺什么、下一步命令或文件。最终答复直接给产物和运行方法，说明实际验证范围。
"""
