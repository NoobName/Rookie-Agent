import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.context import budget, conversation_context, project, tokens
from services.agent.engine import Engine
from services.agent.models import ProviderConfig
from services.agent.providers import OpenAICompatible
from tests.test_core import wait_state
from tests.test_execution import create


def test_budget_uses_actual_window_and_reserves_explicit_output():
    config = ProviderConfig(
        id="x", name="x", model="x", profile={"context_window": 128000}, extra={"max_tokens": 16000}
    )
    b = budget(config, 8000)
    assert b["window"] == 128000 and b["input_limit"] == 102400
    assert b["output_reserve"] == 16000
    assert budget()["window"] is None and budget()["source"] == "local_fallback"
    assert tokens("中文") >= 3
    assert (
        tokens({"type": "image_url", "image_url": {"url": "data:image/png;base64," + "x" * 100000}})
        == 4096
    )


def test_large_closed_tool_batch_compacts_without_replaying_file_write(tmp_path):
    content = "// rendering regression\n" * 10000
    first = {
        "role": "assistant",
        "content": "Create source",
        "reasoning_content": "fixture reasoning",
        "tool_calls": [
            {
                "id": "remote_write",
                "type": "function",
                "function": {
                    "name": "files__write",
                    "arguments": json.dumps({"path": "render.cpp", "content": content}),
                },
            }
        ],
    }
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            msg = first
        else:
            text = json.dumps(body["messages"], ensure_ascii=False)
            assert "本地结构化上下文摘要" in text and "render.cpp" in text
            assert "succeeded" in text and "content_archived" in text
            assert all(m["role"] not in ("assistant", "tool") for m in body["messages"])
            msg = {"role": "assistant", "content": "Source written; review the file."}
        return httpx.Response(200, json={"choices": [{"message": msg}]})

    app = create_app(tmp_path / "data", "t")
    config = ProviderConfig(
        id="fixture", name="fixture", model="fixture", tools=True, streaming=False
    )
    app.state.engine.provider = lambda _: OpenAICompatible(
        config, transport=httpx.MockTransport(handler)
    )
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(c, tools=["files.write"])
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        result = wait_state(c, tid, {"awaiting_feedback", "failed"})
        assert result["state"] == "awaiting_feedback", result
        assert (
            Path(result["spec"]["workspace"], "render.cpp").read_text(encoding="utf-8") == content
        )
        store = app.state.engine.store
        assert len(requests) == 2
        assert len(store.rows("SELECT * FROM calls WHERE task_id=?", (tid,))) == 1
        assert (
            json.loads(
                store.one("SELECT message FROM model_turns WHERE task_id=?", (tid,))["message"]
            )
            == first
        )
        snapshots = store.rows(
            "SELECT payload FROM events WHERE task_id=? AND type='context_compacted'", (tid,)
        )
        assert len(snapshots) == 1
        info = json.loads(snapshots[0]["payload"])
        assert info["input_tokens"] < info["input_limit"] < info["before_tokens"]
        # Projection is recoverable from immutable evidence after an engine reload.
        rebuilt = Engine(store).messages(
            requests[0]["messages"], tid, 120000, "scripted", config, requests[0]["tools"]
        )
        assert rebuilt == requests[1]["messages"]
        assert (
            len(
                store.rows(
                    "SELECT * FROM events WHERE task_id=? AND type='context_compacted'", (tid,)
                )
            )
            == 1
        )


def test_pruning_preserves_complete_protocol_and_failure_evidence():
    assistant = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "keep exact",
        "tool_calls": [
            {
                "id": "call1",
                "type": "function",
                "function": {"name": "files__read", "arguments": '{"path":"x"}'},
            }
        ],
    }
    result = {
        "status": "failed",
        "error": "compile failed",
        "stdout": "head\n" + "x" * 150000 + "\ntail",
        "exit_code": 1,
    }
    tool = {"role": "tool", "tool_call_id": "call1", "content": json.dumps(result)}
    row = {
        "id": "db1",
        "tool": "files.read",
        "status": "failed",
        "args": '{"path":"x"}',
        "result": tool["content"],
    }
    messages, info = project([], [[assistant, tool]], [[row]], [], budget())
    assert messages[0] == assistant and messages[1]["tool_call_id"] == "call1"
    assert "compile failed" in messages[1]["content"] and "tail" in messages[1]["content"]
    assert info["pruned"] and not info["compacted_batches"]


def test_required_prefix_is_never_silently_discarded():
    import pytest

    with pytest.raises(ValueError, match="当前目标或验收条件"):
        project([{"role": "user", "content": "约束" * 50000}], [], [], [], budget())


def test_conversation_excerpt_preserves_boundaries_and_marks_loss():
    rows = [{"id": str(i), "role": "assistant", "content": "旧回答" * 5000} for i in range(10)]
    rows.append({"id": "latest", "role": "user", "content": "下一步继续验证阴影"})
    context = conversation_context(rows, 2000)
    data = json.loads(context.split("：", 1)[1])
    assert data["messages"][-1] == rows[-1]
    assert data["omitted_older_messages"] > 0
    assert tokens(data) < 2100
    assert any(m.get("context_excerpt") for m in data["messages"])


def test_checkpoint_reused_with_new_calls_and_invalidated_on_evidence_change(tmp_path):
    app = create_app(tmp_path / "data", "t")
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(c, tools=["files.write"])
        tid = task["id"]
        store = app.state.engine.store
        store.run(
            "INSERT INTO calls VALUES(?,?,?,?,?,?,?)",
            (
                "old",
                tid,
                "files.write",
                json.dumps({"path": "x", "content": "x" * 240000}),
                "succeeded",
                '{"status":"succeeded"}',
                1,
            ),
        )
        Engine(store).messages([], tid, 120000, "scripted")
        store.run(
            "INSERT INTO calls VALUES(?,?,?,?,?,?,?)",
            (
                "new",
                tid,
                "files.read",
                '{"path":"x"}',
                "succeeded",
                '{"status":"succeeded","text":"new evidence"}',
                2,
            ),
        )
        messages = Engine(store).messages([], tid, 120000, "scripted")
        assert "new evidence" in json.dumps(messages)
        assert (
            len(
                store.rows(
                    "SELECT * FROM events WHERE task_id=? AND type='context_compacted'", (tid,)
                )
            )
            == 1
        )
        latest = json.loads(
            store.one(
                "SELECT payload FROM events WHERE task_id=? AND type='context_budget' ORDER BY id DESC LIMIT 1",
                (tid,),
            )["payload"]
        )
        assert latest["reused_checkpoint"] and latest["before_tokens"] < latest["input_limit"]
        store.run(
            "UPDATE calls SET status='failed',result=? WHERE id='old'",
            (json.dumps({"status": "failed", "error": "corrected evidence"}),),
        )
        messages = Engine(store).messages([], tid, 120000, "scripted")
        assert "corrected evidence" in json.dumps(messages)


def test_task_timing_survives_lots_of_events_and_resume(tmp_path):
    app = create_app(tmp_path / "data", "t")
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(c, tools=[])
        tid = task["id"]
        store = app.state.engine.store
        store.run(
            "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
            (tid, "state", '{"state":"running"}', 100),
        )
        store.many(
            "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
            [(tid, "text", "{}", 200 + i) for i in range(2100)],
        )
        store.run(
            "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
            (tid, "state", '{"state":"waiting_for_user","detail":"step limit"}', 2500),
        )
        store.run("UPDATE tasks SET state='waiting_for_user' WHERE id=?", (tid,))
        stopped = store.task(tid)
        assert (
            stopped["timing"] == {"started": 100, "ended": 2500}
            and stopped["state_detail"] == "step limit"
        )
        store.transition(tid, "running")
        assert store.task(tid)["timing"] == {"started": 100, "ended": None}
