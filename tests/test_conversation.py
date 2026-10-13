import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.models import ProviderConfig
from services.agent.providers import Reply


class ConversationalModel:
    config = ProviderConfig(id="fixture", model="fixture", name="fixture", tools=True)

    def __init__(self, answer_only=False):
        self.seen = []
        self.answer_only = answer_only

    async def reply(self, messages, tools, emit):
        self.seen.append((messages, tools))
        assert tools
        evidence = [m for m in messages if m["role"] == "tool"]
        if self.answer_only or len(evidence) >= 2:
            return Reply(
                "回答完成，文件及命令结果见记录。",
                usage={"prompt_tokens": 20, "completion_tokens": 10},
            )
        if not evidence:
            return Reply(
                calls=[
                    {
                        "id": "write",
                        "name": "files.write",
                        "arguments": {"path": "chat.txt", "content": "actual chat output"},
                    }
                ]
            )
        return Reply(
            calls=[
                {
                    "id": "run",
                    "name": "terminal.run",
                    "arguments": {
                        "argv": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path;assert Path('chat.txt').read_text()=='actual chat output';print('CHAT_VERIFIED')",
                        ]
                    },
                }
            ]
        )


def wait_state(c, tid, states):
    for _ in range(200):
        task = next(t for t in c.get("/api/bootstrap").json()["tasks"] if t["id"] == tid)
        if task["state"] in states:
            return task
        time.sleep(0.02)
    raise AssertionError(task)


@pytest.mark.parametrize("mode", ["ask", "workspace"])
def test_conversation_real_tools_and_approval(tmp_path, mode):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(tmp_path / "data", "test")
    model = ConversationalModel()
    app.state.engine.provider = lambda _: model
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer test"
        pid = c.post("/api/projects", json={"name": "project", "workspace": str(workspace)}).json()[
            "id"
        ]
        sid = c.post("/api/sessions", json={"title": "chat", "project_id": pid}).json()["id"]
        attachment = c.post(
            "/api/attachments", files={"file": ("input.txt", b"ATTACHMENT_PROOF", "text/plain")}
        ).json()["id"]
        response = c.post(
            f"/api/sessions/{sid}/chat",
            json={
                "content": "write and verify file",
                "provider": "fixture",
                "execute": True,
                "mode": mode,
                "attachments": [attachment],
            },
        )
        assert response.status_code == 200, response.text
        tid = response.json()["task_id"]
        task = wait_state(c, tid, {"awaiting_approval"})
        assert task["spec"]["workspace"] == str(workspace)
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        if mode == "ask":
            assert calls[-1]["tool"] == "files.write"
            assert not (workspace / "chat.txt").exists()
            c.post("/api/approvals/" + calls[-1]["id"], json={"allow": True})
            for _ in range(200):
                calls = c.get(f"/api/tasks/{tid}/calls").json()
                if calls[-1]["tool"] == "terminal.run":
                    break
                time.sleep(0.02)
        assert calls[-1]["tool"] == "terminal.run"
        assert (workspace / "chat.txt").read_text() == "actual chat output"
        assert (
            c.post(
                f"/api/sessions/{sid}/chat",
                json={"content": "overlap", "provider": "fixture", "execute": True},
            ).status_code
            == 400
        )
        c.post("/api/approvals/" + calls[-1]["id"], json={"allow": True})
        assert wait_state(c, tid, {"awaiting_feedback", "failed"})["state"] == "awaiting_feedback"
        assert "CHAT_VERIFIED" in c.get(f"/api/tasks/{tid}/calls").json()[-1]["result"]["stdout"]
        assert "ATTACHMENT_PROOF" in json.dumps(model.seen[0], ensure_ascii=False)
        assert "不允许调用执行工具" not in model.seen[0][0][0]["content"]
        assert c.get(f"/api/tasks/{tid}/result").status_code == 200


def test_conversation_answer_and_history(tmp_path):
    app = create_app(tmp_path / "data", "test")
    model = ConversationalModel(True)
    app.state.engine.provider = lambda _: model
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer test"
        sid = c.post("/api/sessions", json={}).json()["id"]
        for prompt in ["first question", "second question"]:
            response = c.post(
                f"/api/sessions/{sid}/chat",
                json={"content": prompt, "provider": "fixture", "execute": True},
            )
            tid = response.json()["task_id"]
            assert wait_state(c, tid, {"completed", "failed"})["state"] == "completed"
            assert c.get(f"/api/tasks/{tid}/calls").json() == []
        assert "first question" in json.dumps(model.seen[-1])


def test_conversation_steering_retains_attachment_and_does_not_repeat_write(tmp_path):
    app = create_app(tmp_path / "data", "test")
    model = ConversationalModel()
    app.state.engine.provider = lambda _: model
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer test"
        sid = c.post("/api/sessions", json={}).json()["id"]
        tid = c.post(
            f"/api/sessions/{sid}/chat",
            json={
                "content": "write and verify",
                "provider": "fixture",
                "execute": True,
                "mode": "workspace",
            },
        ).json()["task_id"]
        wait_state(c, tid, {"awaiting_approval"})
        aid = c.post(
            "/api/attachments", files={"file": ("extra.txt", b"STEERING_ATTACHMENT", "text/plain")}
        ).json()["id"]
        changed = c.post(
            f"/api/tasks/{tid}/feedback",
            json={"content": "also read attached information", "attachments": [aid]},
        )
        assert changed.status_code == 200
        assert aid in changed.json()["spec"]["inputs"]
        assert c.post(f"/api/tasks/{tid}/start", json={}).status_code == 200
        wait_state(c, tid, {"awaiting_approval"})
        calls = c.get(f"/api/tasks/{tid}/calls").json()
        assert len([x for x in calls if x["tool"] == "files.write"]) == 1
        assert any(x["status"] == "not_executed" for x in calls)
        assert "STEERING_ATTACHMENT" in json.dumps(model.seen[-1])
        c.post("/api/approvals/" + calls[-1]["id"], json={"allow": False})
        assert wait_state(c, tid, {"failed"})["state"] == "failed"
        assert c.get(f"/api/tasks/{tid}/calls").json()[-1]["status"] == "not_executed"
