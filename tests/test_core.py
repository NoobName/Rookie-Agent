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
from services.agent.models import ProviderConfig, TaskSpec
from services.agent.policy import PolicyEngine, inside
from services.agent.providers import OpenAICompatible
from services.agent.store import Store, dump, uid
from services.agent.tools import Tools, document, mcp_call


def make_task(store, workspace, mode="workspace"):
    tid = uid()
    spec = TaskSpec(
        goal="test",
        workspace=str(workspace),
        mode=mode,
        deliverables=["hello_agent.py"],
        acceptance=["exit 0"],
    )
    store.run(
        "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
        (tid, "s", "planned", dump(spec.model_dump()), time.time(), time.time()),
    )
    return store.task(tid)


def test_path_and_policy(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = Store(tmp_path / "db")
    task = make_task(store, root)
    with pytest.raises(PermissionError):
        inside(root, "../escape.txt")
    with pytest.raises(PermissionError):
        inside(root, tmp_path / "outside.txt")
    policy = PolicyEngine(store)
    assert policy.allowed(task, "files.write", {"path": "new.txt"}, "call")
    (root / "new.txt").write_text("old")
    assert policy.allowed(task, "files.write", {"path": "new.txt"}, "call")
    assert not policy.allowed(task, "terminal.run", {"argv": ["python"]}, "call")
    grant = policy.grant(task["id"], "terminal.run", "call")
    assert policy.allowed(task, "terminal.run", {}, "call")
    assert not policy.allowed(task, "terminal.run", {}, "other")
    store.run("UPDATE grants SET revoked=1 WHERE id=?", (grant,))
    assert not policy.allowed(task, "terminal.run", {}, "call")


def test_recovery_and_state(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    store = Store(tmp_path / "d")
    task = make_task(store, root)
    with pytest.raises(ValueError):
        store.transition(task["id"], "completed")
    store.transition(task["id"], "running")
    store.recover()
    assert store.task(task["id"])["state"] == "paused"
    assert store.rows("SELECT * FROM events WHERE type=?", ("interrupted",))


async def test_files_and_commands(tmp_path):
    task = {"id": "t", "spec": {"workspace": str(tmp_path)}}
    tools = Tools()
    events = []

    async def emit(k, v):
        events.append((k, v))

    result = await tools.execute(
        task, "files.write", {"path": "含 空格.txt", "content": "你好"}, emit
    )
    assert result["status"] == "succeeded" and "+你好" in result["diff"]
    result = await tools.execute(
        task, "files.write", {"path": "含 空格.txt", "content": "overwrite"}, emit
    )
    assert result["status"] == "failed" and (tmp_path / "含 空格.txt").read_text("utf-8") == "你好"
    result = await tools.execute(
        task,
        "terminal.run",
        {"argv": [sys.executable, "-c", 'import sys; print("real"); sys.exit(3)']},
        emit,
    )
    assert result["exit_code"] == 3 and result["status"] == "failed" and "real" in result["stdout"]
    result = await tools.execute(
        task,
        "terminal.run",
        {"argv": [sys.executable, "-c", "import time;time.sleep(10)"], "timeout": 0.1},
        emit,
    )
    assert result["status"] == "failed" and "超时" in result["error"]


async def test_cancel_process(tmp_path):
    import psutil

    tools = Tools()

    async def emit(*args):
        pass

    run = asyncio.create_task(
        tools.command(
            "t", [sys.executable, "-c", "import time;time.sleep(20)"], str(tmp_path), 60, emit
        )
    )
    for _ in range(100):
        if "t" in tools.processes:
            break
        await asyncio.sleep(0.02)
    pid = tools.processes["t"].pid
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert not psutil.pid_exists(pid)


@pytest.mark.parametrize(
    "extension,content",
    [
        (".docx", "真实文档内容"),
        (".xlsx", '[["名称", "数量"], ["苹果", 3]]'),
        (".pdf", "真实 PDF 验证 Hello"),
    ],
)
def test_documents(tmp_path, extension, content):
    result = document(str(tmp_path), {"path": "output" + extension, "content": content})
    assert (tmp_path / ("output" + extension)).stat().st_size > 100
    assert result["output"]
    reread = document(str(tmp_path), {"path": "output" + extension, "content": None})
    assert reread["output"] == result["output"]


async def test_provider_stream_protocol():
    seen = []

    async def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        chunks = [
            {"choices": [{"delta": {"content": "hello"}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c1",
                                    "function": {"name": "files__read", "arguments": '{"path":'},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"a.txt"}'}}]}}
                ]
            },
            {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 4}},
        ]
        return httpx.Response(
            200,
            content="\n\n".join("data: " + json.dumps(c) for c in chunks) + "\n\ndata: [DONE]\n\n",
        )

    config = ProviderConfig(
        id="test", name="t", base_url="http://localhost:9999/v1/", model="test", tools=True
    )
    provider = OpenAICompatible(config, httpx.MockTransport(handler))
    output = []

    async def emit(t):
        output.append(t)

    result = await provider.reply([], [], emit)
    assert seen[0][0] == "http://localhost:9999/v1/chat/completions"
    assert result.calls[0]["arguments"] == {"path": "a.txt"} and result.usage["prompt_tokens"] == 8
    assert output == ["hello"]


async def test_truncated_protocol_rejected():
    provider = OpenAICompatible(
        ProviderConfig(id="t", name="t", model="t"),
        httpx.MockTransport(lambda request: httpx.Response(200, text='data: {"choices":[]}\n\n')),
    )

    async def emit(t):
        pass

    with pytest.raises(ValueError, match="中断"):
        await provider.reply([], [], emit)


def wait_state(client, tid, states):
    for _ in range(150):
        task = next(t for t in client.get("/api/bootstrap").json()["tasks"] if t["id"] == tid)
        if task["state"] in states:
            return task
        time.sleep(0.03)
    raise AssertionError(task)


def test_end_to_end_real_task_and_auth(tmp_path):
    app = create_app(tmp_path / "data", "test-token")
    with TestClient(app) as client:
        assert client.get("/api/bootstrap").status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        assert (
            client.get("/api/bootstrap", headers={"Origin": "https://evil.test"}).status_code == 403
        )
        sid = client.post("/api/sessions", json={"title": "真实测试"}).json()["id"]
        spec = TaskSpec(
            goal="coding demo",
            workspace="",
            deliverables=["hello_agent.py"],
            acceptance=["exit 0"],
            mode="workspace",
        ).model_dump()
        task = client.post(f"/api/sessions/{sid}/tasks", json=spec).json()
        tid = task["id"]
        assert client.post(f"/api/tasks/{tid}/start", json={}).status_code == 200
        wait_state(client, tid, {"awaiting_approval"})
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert calls[0]["status"] == "succeeded"
        assert calls[1]["tool"] == "terminal.run"
        client.post("/api/approvals/" + calls[1]["id"], json={"allow": True})
        wait_state(client, tid, {"awaiting_feedback"})
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert calls[1]["result"]["exit_code"] == 0 and "PASS" in calls[1]["result"]["stdout"]
        assert (
            client.get(f"/api/tasks/{tid}/artifact", params={"path": "hello_agent.py"}).status_code
            == 200
        )
        assert (
            client.get(f"/api/tasks/{tid}/artifact", params={"path": "../agent.db"}).status_code
            == 403
        )
        client.post(f"/api/tasks/{tid}/accept", json={})
        assert wait_state(client, tid, {"completed"})
    with TestClient(
        create_app(tmp_path / "data", "test-token"), headers={"Authorization": "Bearer test-token"}
    ) as client:
        assert client.get("/api/bootstrap").json()["tasks"][0]["state"] == "completed"


def test_denial_memory_and_queue(tmp_path):
    with TestClient(create_app(tmp_path / "d", "t"), headers={"Authorization": "Bearer t"}) as c:
        sid = c.post("/api/sessions", json={}).json()["id"]
        spec = TaskSpec(
            goal="demo", workspace="", deliverables=["a"], acceptance=["b"]
        ).model_dump()
        a = c.post(f"/api/sessions/{sid}/tasks", json=spec).json()["id"]
        b = c.post(f"/api/sessions/{sid}/tasks", json=spec).json()["id"]
        c.post(f"/api/tasks/{a}/start", json={})
        c.post(f"/api/tasks/{b}/start", json={})
        wait_state(c, a, {"awaiting_approval"})
        tasks = {t["id"]: t for t in c.get("/api/bootstrap").json()["tasks"]}
        assert tasks[b]["state"] == "planned"
        cid = c.get(f"/api/tasks/{a}/calls").json()[0]["id"]
        c.post("/api/approvals/" + cid, json={"allow": False})
        wait_state(c, a, {"failed"})
        wait_state(c, b, {"awaiting_approval"})
        c.post(f"/api/tasks/{b}/cancel", json={})
        wait_state(c, b, {"cancelled"})
        mid = c.put(
            "/api/memories/new", json={"content": "项目使用 SQLite", "scope": "project"}
        ).json()["id"]
        assert len(c.get("/api/memories?q=SQLite").json()) == 1
        c.put("/api/memories/" + mid, json={"content": "项目使用 Postgres"})
        assert not c.get("/api/memories?q=SQLite").json()
        c.delete("/api/memories/" + mid)
        assert not c.get("/api/memories").json()
