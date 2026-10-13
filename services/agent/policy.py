import json
import os
import time
from pathlib import Path

from .store import uid


def inside(workspace, requested):
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("工作区不是目录")
    path = Path(requested)
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        if os.path.normcase(os.path.commonpath([root, path])) != os.path.normcase(str(root)):
            raise PermissionError("路径越出工作区")
    except ValueError:
        raise PermissionError("路径越出工作区")
    return path


class PolicyEngine:
    def __init__(self, store):
        self.store = store

    def allowed(self, task, tool, args, call_id):
        spec = task["spec"]
        if tool == "checks.run":
            from .models import AcceptanceCheck

            planned = [
                AcceptanceCheck.model_validate(c).model_dump() for c in spec.get("checks", [])
            ]
            if args not in planned:
                raise PermissionError("验收检查不在用户计划内")
            if args.get("path"):
                inside(spec["workspace"], args["path"])
        elif tool not in spec["tools"]:
            raise PermissionError("工具不在任务计划授权范围内")
        if tool == "task.plan":
            return True
        if tool in ("files.read", "files.write", "files.edit", "files.search", "document.process"):
            inside(spec["workspace"], args["path"])
        if tool in ("files.list", "workspace.inspect"):
            inside(spec["workspace"], args.get("path", "."))
        if tool == "terminal.run" and args.get("cwd"):
            inside(spec["workspace"], args["cwd"])
        if tool == "document.edit":
            inside(spec["workspace"], args["source"])
            inside(spec["workspace"], args.get("output") or args["source"])
        if tool == "browser.action" and args.get("output"):
            inside(spec["workspace"], args["output"])
        if tool == "browser.action" and args.get("input"):
            inside(spec["workspace"], args["input"])
        if tool == "desktop.action" and args.get("output"):
            inside(spec["workspace"], args["output"])
        grants = self.store.rows(
            "SELECT * FROM grants WHERE task_id=? AND tool=? AND revoked=0 AND expires>?",
            (task["id"], tool, time.time()),
        )
        for g in grants:
            if g["call_id"] == call_id or (g["scope"] == "task" and g["call_id"] is None):
                return True
        for rule in self.store.rows(
            "SELECT * FROM permission_rules WHERE tool=? AND revoked=0 AND expires>?",
            (tool, time.time()),
        ):
            if rule["workspace"] != str(Path(spec["workspace"]).resolve()):
                continue
            if rule["scope"] == "task" and rule["task_id"] != task["id"]:
                continue
            if tool == "terminal.run" and rule["action"] == "terminal_workspace":
                return True
            if json.loads(rule["arguments"]) == args:
                return True
        # Workspace writes still enforce path confinement and optimistic concurrency in Tools.
        if spec["mode"] == "workspace" and tool in (
            "files.read",
            "files.list",
            "workspace.inspect",
            "files.search",
            "git.diff",
            "git.status",
        ):
            return True
        if tool == "checks.run" and (
            args["kind"] == "manual"
            or (spec["mode"] == "workspace" and args["kind"] in ("file_exists", "text_contains"))
        ):
            return True
        if spec["mode"] == "workspace" and tool in (
            "files.write",
            "files.edit",
            "document.edit",
            "document.process",
        ):
            return True
        return False

    def grant(self, task_id, tool, call_id=None, scope="once"):
        ident = uid()
        self.store.run(
            "INSERT INTO grants VALUES(?,?,?,?,?,?,0,?)",
            (ident, task_id, tool, call_id, scope, time.time() + 86400, "user"),
        )
        return ident

    def grant_rule(self, task, tool, args, scope, hours):
        if scope == "workspace_terminal":
            if tool != "terminal.run":
                raise ValueError("工作区终端授权只能用于终端工具")
            ident = uid()
            self.store.run(
                "INSERT INTO permission_rules VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
                (
                    ident,
                    None,
                    str(Path(task["spec"]["workspace"]).resolve()),
                    tool,
                    "terminal_workspace",
                    "user",
                    "workspace",
                    None,
                    "{}",
                    253402214400,
                    "user",
                ),
            )
            return ident
        if scope not in ("task", "workspace") or not 0 < hours <= 168:
            raise ValueError("授权范围或有效期无效")
        ident = uid()
        self.store.run(
            "INSERT INTO permission_rules VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
            (
                ident,
                task["id"] if scope == "task" else None,
                str(Path(task["spec"]["workspace"]).resolve()),
                tool,
                "exact_call",
                "user",
                scope,
                args.get("path"),
                json.dumps(args, ensure_ascii=False),
                time.time() + hours * 3600,
                "user",
            ),
        )
        return ident
