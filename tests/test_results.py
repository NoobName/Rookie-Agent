import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.app import create_app
from tests.test_core import wait_state
from tests.test_execution import create


def test_result_preview_boundary_current_content_and_export(tmp_path):
    app = create_app(tmp_path / "data", "t")
    with TestClient(app, headers={"Authorization": "Bearer t"}) as c:
        task = create(
            c,
            tools=["files.write"],
            script=[
                {
                    "name": "files.write",
                    "arguments": {"path": "proof.html", "content": "<script>alert(1)</script>"},
                }
            ],
        )
        tid = task["id"]
        c.post(f"/api/tasks/{tid}/start", json={})
        wait_state(c, tid, {"awaiting_feedback"})
        result = c.get(f"/api/tasks/{tid}/result").json()
        assert result["state"] == "awaiting_feedback" and result["artifacts"][0]["available"]
        assert result["usage"]["requests"] == 2 and result["usage"]["unknown_cost_requests"] == 2
        assert "reasoning_content" not in json.dumps(result) and "credential_ref" not in json.dumps(
            result
        )
        response = c.get(f"/api/tasks/{tid}/preview", params={"path": "proof.html"})
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["text"] == "<script>alert(1)</script>"
        assert (
            c.get(f"/api/tasks/{tid}/preview", params={"path": "../client.token"}).status_code
            == 403
        )
        assert (
            c.get(f"/api/tasks/{tid}/artifact", params={"path": "../client.token"}).status_code
            == 403
        )
        file = Path(task["spec"]["workspace"]) / "proof.html"
        file.write_text("new contents", "utf-8")
        assert (
            c.get(f"/api/tasks/{tid}/preview", params={"path": "proof.html"}).json()["text"]
            == "new contents"
        )
        file.write_text("x" * 70000, "utf-8")
        value = c.get(f"/api/tasks/{tid}/preview", params={"path": "proof.html"}).json()
        assert value["truncated"] and len(value["text"]) == 65536
        file.write_bytes(b"\x00\xff")
        assert (
            c.get(f"/api/tasks/{tid}/preview", params={"path": "proof.html"}).json()["kind"]
            == "unsupported"
        )
        file.unlink()
        assert c.get(f"/api/tasks/{tid}/result").json()["artifacts"][0]["available"] is False
        assert c.get(f"/api/tasks/{tid}/preview", params={"path": "proof.html"}).status_code == 404
        assert c.get(f"/api/tasks/{tid}/artifact", params={"path": "proof.html"}).status_code == 404
        assert (
            c.get(f"/api/tasks/{tid}/result", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
