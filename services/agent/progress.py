"""Bounded, in-memory progress signals; no file rereads or model calls."""

import hashlib
import json
import os
from collections import deque

NOISE = {
    "started",
    "finished",
    "duration",
    "retrieved",
    "retrieved_at",
    "timestamp",
    "call_id",
    "task_id",
    "change_id",
    "cache_hits",
    "rebuilt_files",
}


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in NOISE}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def digest(value):
    return hashlib.blake2s(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class ProgressTracker:
    def __init__(self, threshold=3, workspace="."):
        self.threshold = threshold
        self.workspace = os.path.abspath(workspace)
        self.recent = deque(maxlen=64)
        self.epoch = 0
        self.warning = None
        self.warned = set()
        self.delivered = set()
        self.pending = set()

    def feedback_delivered(self):
        self.delivered.update(self.pending)
        self.pending.clear()

    def observe(self, name, args, result):
        if result.get("status") != "succeeded" or name == "task.plan":
            return None
        path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    self.workspace,
                    args.get("output") or args.get("path") or args.get("source") or ".",
                )
            )
        )
        editing = name in ("files.edit", "files.write", "document.edit")
        key = ("edit", path) if editing else (name, digest(args))
        if editing:
            version = result.get("sha256") or digest(
                args.get("content", result.get("diff", result.get("output")))
            )
            previous = [entry for entry in self.recent if entry[0] == key]
            repeated = sum(entry[1] == version for entry in previous) + 1
            # Unique edits alone are not proof of a loop. Warn, never stop solely for them.
            kind = (
                "edit_cycle"
                if repeated >= self.threshold
                else "edit_churn" if len(previous) + 1 == self.threshold else None
            )
            self.epoch += 1
            stamp = version
        else:
            evidence = (
                {"sha256": result["sha256"], "offset": args.get("offset", 0)}
                if name == "files.read" and result.get("sha256")
                else stable(result)
            )
            stamp = digest(evidence)
            previous = [
                entry for entry in self.recent if entry[0] == key and entry[2] == self.epoch
            ]
            repeated = sum(entry[1] == stamp for entry in previous) + 1
            kind = "repeated_observation" if repeated >= self.threshold else None
        self.recent.append((key, stamp, self.epoch))
        if not kind:
            return None
        marker = (key, kind)
        if kind == "edit_churn" and marker in self.warned:
            return None
        if len(self.warned) >= 128:
            live = {entry[0] for entry in self.recent}
            self.warned = {m for m in self.warned if m[0] in live}
            self.delivered = {m for m in self.delivered if m[0] in live}
            self.pending = {m for m in self.pending if m[0] in live}
        self.warned.add(marker)
        self.pending.add(marker)
        message = (
            f"同一文件 {path} 已多次修改。请核对修改目的、运行相关验证或改变排查方法；持续修改本身不等于卡死。"
            if kind == "edit_churn"
            else f"检测到 {name} 在同一资源上反复得到相同有效结果或返回旧版本。请使用已有结果、检查根因或改换策略，不要继续重复。"
        )
        self.warning = message
        return {
            "kind": kind,
            "tool": name,
            "resource": path if editing else key[1],
            "count": repeated,
            "detail": message,
            "stop": kind != "edit_churn"
            and marker in self.delivered
            and repeated >= self.threshold + 2,
        }
