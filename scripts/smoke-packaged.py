import json
import os
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / ".runtime/python"))
import httpx

data = Path(os.environ["AGENT_DATA"])
token = (data / "client.token").read_text().strip()
workspace = data / "document-workspace"
workspace.mkdir(exist_ok=True)
with httpx.Client(
    base_url="http://127.0.0.1:" + os.getenv("AGENT_PORT", "8765"),
    headers={"Authorization": "Bearer " + token},
    timeout=20,
) as client:
    assert client.get("/health").json()["ok"]
    assert client.get("/").status_code == 200
    sid = client.post("/api/sessions", json={"title": "Packaged smoke"}).json()["id"]
    spec = {
        "goal": "打包版文档测试",
        "workspace": str(workspace),
        "provider": "scripted",
        "tools": ["document.process"],
        "deliverables": ["proof.docx"],
        "acceptance": ["reparse"],
        "script": [
            {
                "name": "document.process",
                "arguments": {"path": "proof.docx", "content": "Packaged backend document proof"},
            }
        ],
    }
    response = client.post(f"/api/sessions/{sid}/tasks", json=spec)
    response.raise_for_status()
    tid = response.json()["id"]
    client.post(f"/api/tasks/{tid}/start", json={}).raise_for_status()
    for _ in range(100):
        tasks = client.get("/api/bootstrap").json()["tasks"]
        task = next(t for t in tasks if t["id"] == tid)
        if task["state"] == "awaiting_approval":
            calls = client.get(f"/api/tasks/{tid}/calls").json()
            client.post(
                "/api/approvals/" + calls[-1]["id"], json={"allow": True}
            ).raise_for_status()
        if task["state"] in ("awaiting_feedback", "failed"):
            break
        time.sleep(0.1)
    assert task["state"] == "awaiting_feedback", task
    call = client.get(f"/api/tasks/{tid}/calls").json()[-1]
    assert "Packaged backend document proof" in call["result"]["output"]
    assert (workspace / "proof.docx").stat().st_size > 100
print("Packaged EXE: HTTP, authenticated API, actual DOCX creation and reparse passed")
