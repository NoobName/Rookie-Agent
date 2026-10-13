import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.providers import Reply
from services.agent.tool_errors import describe_tool_error
from tests.test_core import wait_state
from tests.test_execution import create


class SequenceProvider:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.requests = []

    async def reply(self, messages, tools, emit):
        self.requests.append(messages)
        action = next(self.actions, None)
        if action is None:
            return Reply("已根据错误修正，请检查文件。")
        calls = [dict(id=f"call-{len(self.requests)}-{i}", **a) for i, a in enumerate(action)]
        assistant = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": c["name"].replace(".", "__"),
                        "arguments": json.dumps(c["arguments"]),
                    },
                }
                for c in calls
            ],
        }
        return Reply(calls=calls, assistant=assistant)


def action(name, **arguments):
    return {"name": name, "arguments": arguments}


def test_invalid_arguments_return_to_model_with_history_and_can_be_repaired(tmp_path):
    provider = SequenceProvider(
        [
            [action("terminal.run")],
            [action("files.write", path="result.txt", content="repaired")],
        ]
    )
    app = create_app(tmp_path / "data", "t")
    app.state.engine.provider = lambda _: provider
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client)
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        assert (
            wait_state(client, tid, {"awaiting_feedback", "failed"})["state"] == "awaiting_feedback"
        )
        feedback = next(m for m in provider.requests[1] if m["role"] == "tool")
        error = json.loads(feedback["content"])["error_info"]
        assert error["type"] == "invalid_arguments"
        assert "argv" in error["message"]
        assert error["suggestion"]
        assert "execution regression" in str(provider.requests[1])
        assert Path(task["spec"]["workspace"], "result.txt").read_text() == "repaired"
        events = client.get(f"/api/tasks/{tid}/events").json()
        assert [e["payload"]["count"] for e in events if e["type"] == "tool_error"] == [1]


def test_error_limit_is_cumulative_stops_batch_and_resets_only_on_continue(tmp_path):
    provider = SequenceProvider(
        [
            [action("files.read", path="missing-1.txt")],
            [action("files.write", path="result.txt", content="kept")],
            [
                action("files.read", path="missing-2.txt"),
                action("files.read", path="missing-3.txt"),
                action("files.write", path="must-not-exist.txt", content="no"),
            ],
        ]
    )
    app = create_app(tmp_path / "data", "t")
    app.state.engine.provider = lambda _: provider
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client)
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        stopped = wait_state(client, tid, {"waiting_for_user", "failed"})
        assert stopped["state"] == "waiting_for_user"
        assert "3/3" in stopped["state_detail"]
        assert "missing-3" in stopped["state_detail"]
        assert len(provider.requests) == 3
        assert not Path(task["spec"]["workspace"], "must-not-exist.txt").exists()
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert len(calls) == 4
        assert [c["result"]["error_info"]["type"] for c in calls if c["status"] == "failed"] == [
            "not_found"
        ] * 3
        # Continuing is an explicit user action; previous calls remain evidence, not replayed.
        client.put(f"/api/tasks/{tid}/spec", json=task["spec"])
        client.post(f"/api/tasks/{tid}/start", json={})
        assert (
            wait_state(client, tid, {"awaiting_feedback", "failed"})["state"] == "awaiting_feedback"
        )
        events = client.get(f"/api/tasks/{tid}/events").json()
        assert len([e for e in events if e["type"] == "tool_error_cycle"]) == 2
        assert len(client.get(f"/api/tasks/{tid}/calls").json()) == 4


def test_configured_error_limit_one(tmp_path):
    with TestClient(
        create_app(tmp_path / "data", "t"), headers={"Authorization": "Bearer t"}
    ) as client:
        task = create(
            client, guardrails={"max_tool_errors": 1}, script=[action("files.read", path="absent")]
        )
        client.post(f"/api/tasks/{task['id']}/start", json={})
        stopped = wait_state(client, task["id"], {"waiting_for_user", "failed"})
        assert stopped["state"] == "waiting_for_user"
        assert "1/1" in stopped["state_detail"]


def test_error_classification_and_output_bounds():
    assert describe_tool_error("terminal.run", {"error": "执行超时"})["type"] == "timeout"
    assert (
        describe_tool_error("files.write", {"error": "SHA256 已变化"})["type"] == "version_conflict"
    )
    assert describe_tool_error("files.read", {"error": "PermissionError: 路径越出工作区"})[
        "requires_user"
    ]
    error = describe_tool_error("terminal.run", {"exit_code": 2, "stderr": "x" * 5000})
    assert error["type"] == "command_exit"
    assert len(error["details"]) == 4000
