import json
import os
import sys
from pathlib import Path

import pytest

from services.agent.policy import inside
from services.agent.tools import mcp_call


async def test_real_mcp_discovery_call_and_failure(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", str(root / ".runtime/python"))
    base = {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(root / "examples/mcp_server.py")],
        "url": "",
        "tool": "",
        "arguments": {},
    }
    discovered = await mcp_call(base)
    assert {t["name"] for t in discovered["tools"]} == {"add", "fail"}
    result = await mcp_call({**base, "tool": "add", "arguments": {"a": 7, "b": 9}})
    assert result["content"][0]["text"] == "16"
    with pytest.raises(RuntimeError, match="MCP"):
        await mcp_call({**base, "tool": "fail"})


def test_junction_escape(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows junction test")
    import subprocess

    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "link"), str(outside)], capture_output=True
    )
    if result.returncode:
        pytest.skip("Junction creation unavailable")
    with pytest.raises(PermissionError):
        inside(root, "link/secret.txt")
    # Remove junction itself, never recursively touch target.
    os.rmdir(root / "link")


async def test_browser_observe_fill_submit_download(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from services.agent.extensions import BrowserArgs, BrowserTools

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/download":
                self.send_response(200)
                self.send_header("Content-Disposition", 'attachment; filename="proof.txt"')
                self.end_headers()
                self.wfile.write(b"real download")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b'<title>Controlled Site</title><form action="/sent"><input name="name" id="name"><button id="submit">Send</button></form><a href="/download" id="download">Download</a>'
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = BrowserTools()
    task = {"id": "browser-test", "spec": {"workspace": str(tmp_path)}}

    async def action(**args):
        return await browser.run(task, BrowserArgs(**args).model_dump())

    try:
        result = await action(action="open", url=f"http://127.0.0.1:{server.server_port}")
        assert result["source"]["title"] == "Controlled Site"
        result = await action(
            action="fill", selector="#name", text="Agent", observation=result["observation"]
        )
        with pytest.raises(ValueError, match="表单提交"):
            await action(action="click", selector="#submit", observation=result["observation"])
        result = await action(action="observe")
        result = await action(
            action="submit", selector="#submit", observation=result["observation"]
        )
        assert "/sent?name=Agent" in result["source"]["url"]
        result = await action(
            action="download",
            selector="#download",
            output="proof.txt",
            observation=result["observation"],
        )
        assert (tmp_path / "proof.txt").read_text() == "real download"
        with pytest.raises(ValueError, match="过期"):
            await action(action="fill", selector="#name", text="bad", observation="stale")
    finally:
        await browser.close()
        server.shutdown()
        server.server_close()


async def test_scheduler_expiry_missed_and_single_fire(tmp_path):
    import time

    from services.agent.models import TaskSpec
    from services.agent.scheduler import Schedule, Scheduler
    from services.agent.store import Store, dump

    store = Store(tmp_path / "db")

    class Queue:
        def __init__(self):
            self.items = []

        async def enqueue(self, tid):
            self.items.append(tid)

    queue = Queue()
    scheduler = Scheduler(store, queue)
    now = time.time()
    base = Schedule(
        name="test",
        session_id="s",
        spec=TaskSpec(goal="demo", workspace=str(tmp_path)),
        next_run=now - 5,
        authorized_until=now + 3600,
    )
    store.run("INSERT INTO schedules VALUES(?,?,?,1)", ("valid", base.model_dump_json(), now - 5))
    expired = base.model_copy(update={"authorized_until": now - 1})
    store.run(
        "INSERT INTO schedules VALUES(?,?,?,1)", ("expired", expired.model_dump_json(), now - 5)
    )
    store.run(
        "INSERT INTO schedules VALUES(?,?,?,1)", ("missed", base.model_dump_json(), now - 100)
    )
    await scheduler.tick(now)
    await scheduler.tick(now + 1)
    assert len(queue.items) == 1
    assert store.one("SELECT enabled FROM schedules WHERE id=?", ("expired",))["enabled"] == 0


async def test_bounded_collaboration_mapping_and_no_tools():
    from services.agent.collaboration import collaborate
    from services.agent.providers import Reply

    class Provider:
        def __init__(self, text):
            self.text = text
            self.calls = 0

        async def reply(self, messages, tools, emit):
            assert tools == []
            self.calls += 1
            return Reply(self.text)

    main = Provider(
        '{"assignments":[{"role":"review","provider":"reviewer","objective":"review design","acceptance":["identify risks"]}]}'
    )
    sub = Provider("Suggestions, not proof")
    events = []

    async def emit(k, p):
        events.append((k, p))

    async def usage(*args):
        pass

    results = await collaborate(main, lambda _: sub, [], {"review": "reviewer"}, emit, usage)
    assert sub.calls == 1 and "未验证" in results[0]["verification"]
    with pytest.raises(PermissionError):
        await collaborate(main, lambda _: sub, [], {"review": "other"}, emit, usage)
