"""Exercise authorized desktop tools against the synthetic Electron fixture only.
Run with an isolated AGENT_DATA and AGENT_PORT. Never selects a user app.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = Path(os.environ["AGENT_DATA"]).resolve()
if not data.is_relative_to(root / ".runtime"):
    raise SystemExit("Use isolated .runtime data")
token = (data / "client.token").read_text().strip()
base = "http://127.0.0.1:" + os.environ["AGENT_PORT"]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(route, body=None):
    request = urllib.request.Request(
        base + "/api" + route,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def run(args):
    sid = api("/sessions", {"title": "Windows synthetic fixture smoke"})["id"]
    task = api(
        "/sessions/" + sid + "/tasks",
        {
            "goal": "Validate own UIA fixture",
            "workspace": "",
            "provider": "scripted",
            "tools": ["desktop.action"],
            "deliverables": ["UIA evidence"],
            "acceptance": ["Check synthetic fixture"],
            "script": [{"name": "desktop.action", "arguments": args}],
        },
    )
    tid = task["id"]
    api("/tasks/" + tid + "/start", {})
    approved = set()
    for _ in range(200):
        calls = api("/tasks/" + tid + "/calls")
        for call in calls:
            if call["status"] == "pending" and call["id"] not in approved:
                api("/approvals/" + call["id"], {"allow": True})
                approved.add(call["id"])
        task = next(t for t in api("/bootstrap")["tasks"] if t["id"] == tid)
        if task["state"] in ("failed", "awaiting_feedback", "waiting_for_user"):
            if not calls or calls[-1]["status"] != "succeeded":
                raise RuntimeError(json.dumps(calls[-1]["result"] if calls else task))
            return calls[-1]["result"]
        time.sleep(0.1)
    raise RuntimeError("Smoke timeout")


state_path = data / "windows-smoke.json"
phase = sys.argv[1]
if phase == "observe":
    api("/desktop/arm", {})
    windows = run({"action": "windows"})["output"]
    matches = [w for w in windows if w["title"] == "Local Agent Desktop Test Fixture"]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one synthetic fixture window")
    hwnd = matches[0]["hwnd"]
    value = run({"action": "observe", "hwnd": hwnd})
    value["hwnd"] = hwnd
elif phase == "focus":
    value = json.loads(state_path.read_text())
    value = run({"action": "focus", "hwnd": value["hwnd"], "observation": value["observation"]})
    value["hwnd"] = value["target"]
elif phase == "type":
    value = json.loads(state_path.read_text())
    controls = [c for c in value["output"] if c["type"] == "Edit" and c["title"] == "Smoke input"]
    if len(controls) != 1:
        raise RuntimeError("Expected one observed editable fixture control")
    value = run(
        {
            "action": "type",
            "hwnd": value["hwnd"],
            "observation": value["observation"],
            "control_id": controls[0]["id"],
            "text": "Agent UIA proof 123",
        }
    )
    value["hwnd"] = value["target"]
elif phase == "stopped":
    desktop = api("/bootstrap")["desktop"]
    assert desktop["stopped"], "Hotkey did not stop desktop input"
    print("Emergency stop is active")
    sys.exit(0)
else:
    raise SystemExit("Use observe, focus, type, or stopped")
state_path.write_text(json.dumps(value), "utf-8")
print(
    json.dumps(
        {k: value[k] for k in ("output", "observation", "hwnd", "stopped") if k in value},
        ensure_ascii=False,
    )
)
