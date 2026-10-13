"""Versioned, repeatable evaluations use normal tasks and normal approvals."""

import json
import shutil
import sys
import time
from pathlib import Path

from .models import TaskSpec
from .store import dump, uid


def create_evaluation(store, provider, suite):
    if suite not in ("coding", "documents"):
        raise ValueError("评测类型必须为 coding 或 documents")
    config = json.loads(store.one("SELECT config FROM providers WHERE id=?", (provider,))["config"])
    if not config.get("tools"):
        raise ValueError("评测任务需要已启用原生工具能力")
    interpreter = shutil.which("python") if getattr(sys, "frozen", False) else sys.executable
    if not interpreter:
        raise ValueError("评测需要本机 Python 解释器")
    sid = uid()
    tid = uid()
    folder = store.root / "evaluations" / tid
    folder.mkdir(parents=True)
    store.run("INSERT INTO sessions VALUES(?,?,?)", (sid, "能力评测 · " + suite, time.time()))
    if suite == "coding":
        goal = "创建 solution.py，实现 normalize(values)：去重并升序排序整数列表，不修改输入。创建后运行测试。不要更改验收命令。"
        code = "import runpy\nf=runpy.run_path('solution.py')['normalize']\ncases=[([],[]),([3,1,3,2],[1,2,3]),([-2,0,-2,5],[-2,0,5]),([7],[7])]\nfor values,expected in cases:\n    before=values.copy()\n    assert f(values)==expected\n    assert values==before\nprint('4 cases passed')"
        deliverables = ["solution.py"]
        tools = ["files.read", "files.write", "terminal.run"]
        checks = [
            {
                "id": "functional",
                "label": "四组实际 Python 验收",
                "kind": "command",
                "argv": [interpreter, "-c", code],
            }
        ]
    else:
        goal = "使用 document.process 创建 report.docx，正文准确包含“项目状态：已完成”和“下一步：人工复核”。不要用终端伪造检查。"
        deliverables = ["report.docx"]
        tools = ["document.process"]
        # The fixed verifier reads actual DOCX XML using only the standard library.
        code = "import zipfile,xml.etree.ElementTree as E;z=zipfile.ZipFile('report.docx');text=''.join(E.fromstring(z.read('word/document.xml')).itertext());assert '项目状态：已完成' in text and '下一步：人工复核' in text;print('DOCX content passed')"
        checks = [
            {
                "id": "docx",
                "label": "实际 DOCX 内容检查",
                "kind": "command",
                "argv": [interpreter, "-c", code],
            }
        ]
    spec = TaskSpec(
        goal=goal,
        workspace=str(folder.resolve()),
        provider=provider,
        deliverables=deliverables,
        acceptance=["固定机器检查通过；人工检查产物"],
        tools=tools,
        checks=checks,
    )
    now = time.time()
    store.run(
        "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
        (tid, sid, "planned", spec.model_dump_json(), now, now),
    )
    store.run(
        "INSERT INTO evaluations VALUES(?,?,?,?,?,?)",
        (uid(), tid, provider, config["model"], suite, now),
    )
    store.event(
        tid,
        "evaluation",
        {
            "suite": suite,
            "version": 1,
            "detail": "未开始；费用与工具执行仍需用户启动和授权。不是通用能力排名。",
        },
    )
    return store.task(tid)


def history(store):
    results = []
    for row in store.rows("SELECT * FROM evaluations ORDER BY created DESC LIMIT 100"):
        try:
            task = store.task(row["task_id"])
        except KeyError:
            continue
        verification = task["verification"]
        checks = verification.get("checks", []) if verification else []
        passed = (
            bool(checks)
            and all(c["status"] == "succeeded" for c in checks)
            and not verification.get("unresolved_calls")
        )
        results.append(
            {
                **row,
                "version": 1,
                "state": task["state"],
                "machine_passed": passed,
                "user_accepted": task["state"] == "completed",
                "samples": 1,
            }
        )
    return results
