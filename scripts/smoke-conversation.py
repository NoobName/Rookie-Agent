"""Isolated HTTP-provider protocol smoke; real backend writes a real file, no paid API."""

import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = Path(os.environ["AGENT_DATA"]).resolve()
if not data.is_relative_to(root / ".runtime"):
    raise RuntimeError("Use isolated AGENT_DATA under .runtime")
seen = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append(body)
        if any(m["role"] == "tool" for m in body["messages"]):
            message = {
                "role": "assistant",
                "content": "已写入 proof.txt，工具返回成功；请查看产物。",
            }
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "proof-call",
                        "type": "function",
                        "function": {
                            "name": "files__write",
                            "arguments": json.dumps(
                                {"path": "proof.txt", "content": "CONVERSATION_HTTP_PROOF"}
                            ),
                        },
                    }
                ],
            }
        result = json.dumps(
            {
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 32, "completion_tokens": 10},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(result)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
token = (data / "client.token").read_text().strip()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        "http://127.0.0.1:" + os.environ["AGENT_PORT"] + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with opener.open(req, timeout=15) as response:
        return json.load(response)


try:
    ident = "conversation_http_" + str(time.time_ns())
    api(
        "/providers/" + ident,
        "PUT",
        {
            "id": ident,
            "name": "Local protocol fixture",
            "model": "fixture",
            "tools": True,
            "streaming": False,
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        },
    )
    sid = api("/sessions", "POST", {"title": "HTTP conversation smoke"})["id"]
    result = api(
        "/sessions/" + sid + "/chat",
        "POST",
        {"execute": True, "content": "创建 proof.txt 文件", "provider": ident, "mode": "workspace"},
    )
    tid = result["task_id"]
    for _ in range(150):
        task = next(t for t in api("/bootstrap")["tasks"] if t["id"] == tid)
        if task["state"] in ("awaiting_feedback", "failed"):
            break
        time.sleep(0.1)
    assert task["state"] == "awaiting_feedback", task["state"]
    assert (Path(result["workspace"]) / "proof.txt").read_text() == "CONVERSATION_HTTP_PROOF"
    assert (
        len(seen) == 2
        and seen[0]["tools"]
        and any(m["role"] == "tool" for m in seen[1]["messages"])
    )
    print(
        "PASS: HTTP tool protocol, direct-send queue, automatic safe write and actual file artifact; local fixture model."
    )
finally:
    server.shutdown()
    server.server_close()
