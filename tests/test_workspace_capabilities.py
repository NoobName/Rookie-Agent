import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.store import Store
from services.agent.task_plan import plan_context
from services.agent.workspace import FileEdit, WorkspaceInspect, edit_file, inspect_workspace
from tests.test_core import wait_state
from tests.test_execution import create
from tests.test_tool_errors import SequenceProvider, action


def test_inspection_finds_nested_build_scripts_without_running_them(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({"scripts": {"test": "node test.js"}}))
    (project / "node_modules").mkdir()
    (project / "node_modules" / "hidden.txt").write_text("dependency")
    result = inspect_workspace(tmp_path, WorkspaceInspect().model_dump())
    assert result["projects"] == [
        {"kind": "node", "path": "app/package.json", "scripts": {"test": "node test.js"}}
    ]
    assert "app/node_modules/hidden.txt" not in [item["path"] for item in result["output"]]
    assert result["environment"]["os"]


def test_local_edit_preserves_large_file_bom_crlf_and_is_all_or_nothing(tmp_path):
    path = tmp_path / "source.py"
    original = (
        b"\xef\xbb\xbf" + b"# unchanged\r\n" * 100000 + b"def add(a, b):\r\n    return a - b\r\n"
    )
    path.write_bytes(original)
    args = FileEdit(
        path="source.py",
        expected_sha256=hashlib.sha256(original).hexdigest(),
        edits=[
            {"old": "def add(a, b):\n    return a - b", "new": "def add(a, b):\n    return a + b"}
        ],
    ).model_dump()
    bad = {**args, "edits": [*args["edits"], {"old": "missing", "new": "", "expected_matches": 1}]}
    with pytest.raises(ValueError, match="匹配"):
        edit_file(tmp_path, bad)
    assert path.read_bytes() == original
    result = edit_file(tmp_path, args)
    assert path.read_bytes() == original.replace(b"return a - b", b"return a + b")
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "+    return a + b" in result["diff"]


def test_agent_repairs_existing_project_and_runs_real_test(tmp_path):
    app = create_app(tmp_path / "data", "t")
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client)
        root = Path(task["spec"]["workspace"])
        (root / "src").mkdir()
        source = root / "src" / "lighting.py"
        original = "def diffuse(normal, light):\n    return min(0, sum(a*b for a,b in zip(normal, light)))\n"
        source.write_bytes(original.encode("utf-8"))
        (root / "test_lighting.py").write_text(
            'from src.lighting import diffuse\nassert diffuse((0,0,1), (0,0,1)) == 1\nassert diffuse((0,0,1), (0,0,-1)) == 0\nprint("Lighting tests passed")\n'
        )
        plan = {
            "steps": [{"title": "修复漫反射并运行测试", "status": "in_progress"}],
            "summary": "沿用已有 Python 项目",
            "next_action": "读取光照函数",
        }
        provider = SequenceProvider(
            [
                [action("workspace.inspect")],
                [action("task.plan", **plan)],
                [action("files.read", path="src/lighting.py")],
                [
                    action(
                        "files.edit",
                        path="src/lighting.py",
                        expected_sha256=hashlib.sha256(original.encode()).hexdigest(),
                        edits=[{"old": "return min(0,", "new": "return max(0,"}],
                    )
                ],
                [action("terminal.run", argv=[sys.executable, "test_lighting.py"])],
                [
                    action(
                        "task.plan",
                        steps=[{"title": "修复漫反射并运行测试", "status": "completed"}],
                        summary="真实测试通过",
                        next_action="向用户说明修复",
                    )
                ],
            ]
        )
        app.state.engine.provider = lambda _: provider
        tid = task["id"]
        app.state.engine.policy.grant(tid, "terminal.run", scope="task")
        client.post(f"/api/tasks/{tid}/start", json={})
        assert (
            wait_state(client, tid, {"awaiting_feedback", "waiting_for_user", "failed"})["state"]
            == "awaiting_feedback"
        )
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert len(calls) == 6
        assert all(call["status"] == "succeeded" for call in calls), calls
        assert "Lighting tests passed" in str(calls[4]["result"])
        assert "return max(0," in source.read_text()
        assert "读取光照函数" in str(provider.requests[3])
        # The working plan survives reopening the database and does not replace acceptance.
        restored = Store(tmp_path / "data")
        assert "真实测试通过" in str(plan_context(restored, tid))
        assert restored.task(tid)["spec"]["acceptance"] == task["spec"]["acceptance"]
