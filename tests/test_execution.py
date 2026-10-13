import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.models import TaskSpec
from services.agent.providers import Reply
from tests.test_core import wait_state


def create(client, **kwargs):
    sid = client.post("/api/sessions", json={}).json()["id"]
    spec = TaskSpec(
        goal="execution regression",
        workspace="",
        deliverables=["result.txt"],
        acceptance=["review actual output"],
        mode="workspace",
        **kwargs,
    )
    response = client.post(f"/api/sessions/{sid}/tasks", json=spec.model_dump())
    assert response.status_code == 200, response.text
    return response.json()


def approve_until_done(client, tid):
    approved = set()
    for _ in range(300):
        task = next(t for t in client.get("/api/bootstrap").json()["tasks"] if t["id"] == tid)
        if task["state"] in ("failed", "awaiting_feedback", "waiting_for_user"):
            return task
        for call in client.get(f"/api/tasks/{tid}/calls").json():
            if call["status"] == "pending" and call["id"] not in approved:
                assert (
                    client.post("/api/approvals/" + call["id"], json={"allow": True}).status_code
                    == 200
                )
                approved.add(call["id"])
        time.sleep(0.03)
    raise AssertionError(task)


def test_failed_command_can_be_repaired_and_independently_verified(tmp_path):
    before = 'raise AssertionError("broken")\n'
    after = 'print("REPAIRED")\n'
    command = {"name": "terminal.run", "arguments": {"argv": [sys.executable, "result.py"]}}
    script = [
        {"name": "files.write", "arguments": {"path": "result.py", "content": before}},
        command,
        {
            "name": "files.write",
            "arguments": {
                "path": "result.py",
                "content": after,
                "expected_sha256": hashlib.sha256(before.encode()).hexdigest(),
            },
        },
        command,
    ]
    with TestClient(create_app(tmp_path / "data", "t"), headers={"Authorization": "Bearer t"}) as c:
        task = create(
            c,
            script=script,
            checks=[
                {
                    "id": "run",
                    "label": "真实运行",
                    "kind": "command",
                    "argv": [sys.executable, "result.py"],
                },
                {
                    "id": "text",
                    "label": "修复内容",
                    "kind": "text_contains",
                    "path": "result.py",
                    "contains": "REPAIRED",
                },
            ],
        )
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        result = approve_until_done(c, tid)
        assert result["state"] == "awaiting_feedback", result
        assert not result["verification"]["unresolved_calls"]
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert [x["status"] for x in calls if x["tool"] == "terminal.run"] == [
            "failed",
            "succeeded",
        ]
        assert all(x["status"] == "succeeded" for x in result["verification"]["checks"])
        assert calls[-2]["result"]["stdout"].strip() == "REPAIRED"
        assert c.post(f"/api/tasks/{tid}/accept", json={}).status_code == 200


def test_check_result_is_reported_without_automatic_repair_or_task_failure(tmp_path):
    class Provider:
        def __init__(self):
            self.n = 0
            self.messages = []

        async def reply(self, messages, tools, emit):
            self.messages.append(messages)
            self.n += 1
            if self.n == 2:
                return Reply(
                    calls=[
                        {
                            "id": "fix",
                            "name": "files.write",
                            "arguments": {"path": "result.txt", "content": "verified content"},
                        }
                    ]
                )
            return Reply("模型宣称完成")

    app = create_app(tmp_path / "data", "t")
    p = Provider()
    app.state.engine.provider = lambda _: p
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(
            c,
            checks=[
                {
                    "id": "actual",
                    "label": "读取实际文件",
                    "kind": "text_contains",
                    "path": "result.txt",
                    "contains": "verified content",
                }
            ],
        )
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        done = wait_state(c, tid, {"awaiting_feedback", "failed"})
        assert done["state"] == "awaiting_feedback"
        assert not Path(task["spec"]["workspace"], "result.txt").exists()
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert [x["status"] for x in calls if x["tool"] == "checks.run"] == ["failed"]
        assert p.n == 1


def test_user_can_accept_after_reviewing_failed_checks_and_manual_is_not_passed(tmp_path):
    with TestClient(create_app(tmp_path / "data", "t"), headers={"Authorization": "Bearer t"}) as c:
        task = create(
            c,
            script=[{"name": "files.list", "arguments": {}}],
            tools=["files.list"],
            checks=[
                {
                    "id": "missing",
                    "label": "不存在的文件",
                    "kind": "file_exists",
                    "path": "absent.txt",
                },
                {"id": "human", "label": "人工检查", "kind": "manual"},
            ],
        )
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        done = wait_state(c, tid, {"awaiting_feedback"})
        assert [x["status"] for x in done["verification"]["checks"]] == [
            "failed",
            "manual_required",
        ]
        assert c.post(f"/api/tasks/{tid}/accept", json={}).status_code == 200


def test_feedback_invalidates_pending_call_and_restart_resumes_without_rewrite(tmp_path):
    data = tmp_path / "data"
    with TestClient(create_app(data, "t"), headers={"Authorization": "Bearer t"}) as c:
        task = create(c)
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        wait_state(c, tid, {"awaiting_approval"})
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert calls[0]["status"] == "succeeded"
        old = calls[1]["id"]
        response = c.post(
            f"/api/tasks/{tid}/feedback", json={"content": "保留已生成文件，只继续运行测试"}
        )
        assert response.status_code == 200 and response.json()["state"] == "planned"
        assert c.post("/api/approvals/" + old, json={"allow": True}).status_code == 400
        assert c.get(f"/api/tasks/{tid}/calls").json()[1]["status"] == "not_executed"
    with TestClient(create_app(data, "t"), headers={"Authorization": "Bearer t"}) as c:
        c.post(f"/api/tasks/{tid}/start", json={})
        done = approve_until_done(c, tid)
        assert done["state"] == "awaiting_feedback", done
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert len([x for x in calls if x["tool"] == "files.write"]) == 1
        assert calls[-1]["result"]["exit_code"] == 0


@pytest.mark.parametrize("decision", ["skip", "retry"])
def test_interrupted_side_effect_requires_explicit_recovery(tmp_path, decision):
    # The process writes before sleeping: cancellation cannot prove nothing happened.
    source = "from pathlib import Path;import time;p=Path('side-effect.txt');p.write_text(p.read_text()+'x' if p.exists() else 'x');time.sleep(1)"
    data = tmp_path / "data"
    with TestClient(create_app(data, "t"), headers={"Authorization": "Bearer t"}) as c:
        task = create(
            c,
            script=[
                {"name": "terminal.run", "arguments": {"argv": [sys.executable, "-c", source]}}
            ],
        )
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        wait_state(c, tid, {"awaiting_approval"})
        call = c.get(f"/api/tasks/{tid}/calls").json()[0]
        c.post("/api/approvals/" + call["id"], json={"allow": True})
        path = Path(task["spec"]["workspace"]) / "side-effect.txt"
        for _ in range(100):
            if path.exists():
                break
            time.sleep(0.01)
        assert path.read_text() == "x"
        c.post(f"/api/tasks/{tid}/pause", json={})
        c.put(f"/api/tasks/{tid}/spec", json=task["spec"])
        assert c.post(f"/api/tasks/{tid}/start", json={}).status_code == 400
    with TestClient(create_app(data, "t"), headers={"Authorization": "Bearer t"}) as c:
        assert (
            c.post(
                f"/api/tasks/{tid}/recover",
                json={
                    "call_id": call["id"],
                    "decision": decision,
                    "note": "检查实际文件，已有一次写入",
                },
            ).status_code
            == 200
        )
        assert c.post(f"/api/tasks/{tid}/start", json={}).status_code == 200
        done = approve_until_done(c, tid)
        assert done["state"] == "awaiting_feedback", done
        assert path.read_text() == ("xx" if decision == "retry" else "x")
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert calls[0]["status"] == "interrupted" and calls[0]["decision"] == decision


def test_transient_response_retry_does_not_duplicate_tool(tmp_path):
    class Provider:
        def __init__(self):
            self.n = 0

        async def reply(self, messages, tools, emit):
            self.n += 1
            if self.n == 1:
                raise httpx.ReadTimeout("connection lost before dispatch")
            if self.n == 2:
                return Reply(
                    calls=[
                        {
                            "id": "one",
                            "name": "files.write",
                            "arguments": {"path": "result.txt", "content": "once"},
                        }
                    ]
                )
            return Reply("done")

    app = create_app(tmp_path / "data", "t")
    p = Provider()
    app.state.engine.provider = lambda _: p
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(c, guardrails={"retry_delay": 0})
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        wait_state(c, tid, {"awaiting_feedback"})
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert len(calls) == 1 and calls[0]["status"] == "succeeded"
        assert p.n == 3
        assert (
            len(
                [
                    e
                    for e in c.get(f"/api/tasks/{tid}/events").json()
                    if e["type"] == "provider_retry"
                ]
            )
            == 1
        )


def test_provider_cannot_override_acceptance_check(tmp_path):
    with TestClient(create_app(tmp_path / "data", "t"), headers={"Authorization": "Bearer t"}) as c:
        task = create(
            c,
            script=[
                {
                    "name": "checks.run",
                    "arguments": {"id": "fake", "label": "fake", "kind": "manual"},
                }
            ],
            tools=["files.list"],
        )
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        wait_state(c, tid, {"failed"})
        assert not c.get(f"/api/tasks/{tid}/calls").json()


def test_reusable_permission_is_exact_expiring_and_revocable(tmp_path):
    from services.agent.models import Command
    from services.agent.policy import PolicyEngine
    from services.agent.store import Store
    from tests.test_core import make_task

    root = tmp_path / "w"
    root.mkdir()
    store = Store(tmp_path / "db")
    task = make_task(store, root)
    p = PolicyEngine(store)
    args = Command(argv=[sys.executable, "-c", "print(1)"]).model_dump()
    ident = p.grant_rule(task, "terminal.run", args, "task", 1)
    assert p.allowed(task, "terminal.run", args, "new-call")
    changed = {**args, "argv": [sys.executable, "-c", "print(2)"]}
    assert not p.allowed(task, "terminal.run", changed, "new-call")
    other = make_task(store, root)
    assert not p.allowed(other, "terminal.run", args, "new-call")
    store.run("UPDATE permission_rules SET expires=0 WHERE id=?", (ident,))
    assert not p.allowed(task, "terminal.run", args, "new-call")
    ident = p.grant_rule(task, "terminal.run", args, "workspace", 1)
    assert p.allowed(other, "terminal.run", args, "new-call")
    store.run("UPDATE permission_rules SET revoked=1 WHERE id=?", (ident,))
    assert not p.allowed(other, "terminal.run", args, "new-call")


def test_shutdown_refuses_active_execution(tmp_path):
    app = create_app(tmp_path / "data", "t")
    stopped = []
    app.state.shutdown = lambda: stopped.append(True)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(c)
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        wait_state(c, tid, {"awaiting_approval"})
        assert c.post("/api/shutdown").status_code == 400 and not stopped
        c.post(f"/api/tasks/{tid}/pause", json={})
        assert c.post("/api/shutdown").status_code == 200
        assert c.post("/api/sessions", json={}).status_code == 503
        time.sleep(0.3)
        assert stopped
