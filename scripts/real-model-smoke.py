"""Bounded opt-in real model evaluation using synthetic tasks only.
Requires isolated AGENT_DATA populated with a configured provider reference.
Never starts automatically from unit tests or packaging.
"""

import ast
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = Path(os.environ["AGENT_DATA"]).resolve()
if not data.is_relative_to(root / ".runtime"):
    raise SystemExit("Use an isolated .runtime directory")
token = (data / "client.token").read_text().strip()
base = "http://127.0.0.1:" + os.environ["AGENT_PORT"]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(route, body=None, method=None):
    req = urllib.request.Request(
        base + "/api" + route,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with opener.open(req, timeout=120) as response:
        return json.load(response)


def safe_function(source):
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "normalize" or functions[0].decorator_list:
        return False
    allowed = (
        ast.Module,
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.Return,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Expr,
        ast.Constant,
        ast.Subscript,
        ast.ImportFrom,
        ast.alias,
        ast.If,
        ast.Compare,
        ast.Eq,
        ast.Assign,
        ast.List,
        ast.Store,
    )
    if any(not isinstance(n, allowed) for n in ast.walk(tree)):
        return False
    if any(
        isinstance(n, ast.Name)
        and n.id
        not in (
            "values",
            "sorted",
            "set",
            "list",
            "int",
            "Iterable",
            "List",
            "__name__",
            "sample",
            "print",
            "normalize",
        )
        for n in ast.walk(tree)
    ):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (
            node.level
            or node.module not in ("typing", "__future__")
            or any(
                alias.name not in ("Iterable", "List", "annotations") or alias.asname
                for alias in node.names
            )
        ):
            return False
    return all(
        isinstance(n.func, ast.Name) and n.func.id in ("sorted", "set", "print", "normalize")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    )


provider = next(p["id"] for p in api("/bootstrap")["providers"] if p["id"] != "scripted")
reports = (
    json.loads((data / "real-model-results.json").read_text("utf-8"))
    if (data / "real-model-results.json").exists()
    else []
)
for suite in [a for a in sys.argv[1:] if a != "--resume"] or ["documents"]:
    existing = (
        [r for r in api("/evaluations") if r["suite"] == suite and r["state"] == "paused"]
        if "--resume" in sys.argv
        else []
    )
    task = (
        next(t for t in api("/bootstrap")["tasks"] if t["id"] == existing[0]["task_id"])
        if existing
        else api("/evaluations", {"provider": provider, "suite": suite})
    )
    tid = task["id"]
    spec = task["spec"]
    spec["guardrails"]["max_steps"] = 6
    spec["guardrails"]["provider_retries"] = 1
    spec["hard_token_budget"] = 30000
    task = api("/tasks/" + tid + "/spec", spec, "PUT")
    api("/tasks/" + tid + "/start", {})
    approved = set()
    reviewed = False
    deadline = time.time() + 180
    try:
        while time.time() < deadline:
            task = next(t for t in api("/bootstrap")["tasks"] if t["id"] == tid)
            if task["state"] in ("failed", "awaiting_feedback", "waiting_for_user"):
                reports.append(
                    {
                        "suite": suite,
                        "task_id": tid,
                        "state": task["state"],
                        "verification": task["verification"],
                    }
                )
                break
            for call in api("/tasks/" + tid + "/calls"):
                if call["status"] != "pending" or call["id"] in approved:
                    continue
                args = call["args"]
                allow = False

                def same_path(expected):
                    candidate = Path(args.get("path", ""))
                    workspace = Path(spec["workspace"]).resolve()
                    return (
                        candidate if candidate.is_absolute() else workspace / candidate
                    ).resolve() == workspace / expected

                if suite == "documents" and call["tool"] == "document.process":
                    allow = same_path("report.docx") and (
                        args.get("content") is None
                        or (isinstance(args["content"], str) and len(args["content"]) < 10000)
                    )
                if suite == "coding" and call["tool"] == "files.write":
                    allow = same_path("solution.py") and safe_function(args["content"])
                    reviewed = allow
                if call["tool"] == "files.read":
                    allow = same_path("solution.py")
                if call["tool"] == "checks.run":
                    allow = args["argv"] == spec["checks"][0]["argv"] and (
                        suite == "documents" or reviewed
                    )
                if call["tool"] == "terminal.run":
                    allow = (
                        suite == "coding" and reviewed and args["argv"] == spec["checks"][0]["argv"]
                    )
                if not allow:
                    api("/tasks/" + tid + "/pause", {})
                    raise RuntimeError(
                        "Unreviewed tool request; paused without executing: " + call["tool"]
                    )
                api("/approvals/" + call["id"], {"allow": True})
                approved.add(call["id"])
            time.sleep(0.3)
        else:
            api("/tasks/" + tid + "/pause", {})
            raise RuntimeError("Evaluation deadline reached; paused")
    finally:
        (data / "real-model-results.json").write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), "utf-8"
        )
print(json.dumps(reports, ensure_ascii=False))
if any(r["state"] != "awaiting_feedback" for r in reports):
    raise SystemExit(1)
