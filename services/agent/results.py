"""Read-only result views built from recorded execution evidence."""

import json

from .policy import inside

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".csv",
    ".html",
    ".css",
    ".svg",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".sql",
    ".log",
}


def recorded_artifacts(store, tid):
    paths = {}
    for call in store.rows(
        "SELECT id,tool,result FROM calls WHERE task_id=? AND status='succeeded' ORDER BY created,rowid",
        (tid,),
    ):
        for path in json.loads(call["result"] or "{}").get("artifacts", []):
            paths[path] = {"path": path, "call_id": call["id"], "tool": call["tool"]}
    return list(paths.values())


def artifact_path(store, tid, path):
    task = store.task(tid)
    if path not in {a["path"] for a in recorded_artifacts(store, tid)}:
        raise PermissionError("只能查看已记录的任务产物")
    resolved = inside(task["spec"]["workspace"], path)
    if not resolved.is_file():
        raise FileNotFoundError("产物文件已不存在或不是普通文件")
    return resolved


def preview(store, tid, path):
    resolved = artifact_path(store, tid, path)
    size = resolved.stat().st_size
    result = {
        "path": path,
        "size": size,
        "modified": resolved.stat().st_mtime,
        "kind": "unsupported",
        "text": None,
        "truncated": False,
    }
    if resolved.suffix.lower() not in TEXT_SUFFIXES:
        result["detail"] = "此格式暂不支持在线预览，请下载后查看。"
        return result
    with resolved.open("rb") as source:
        raw = source.read(65537)
    truncated = len(raw) > 65536
    try:
        text = raw[:65536].decode("utf-8-sig", errors="strict" if not truncated else "replace")
    except UnicodeDecodeError:
        result["detail"] = "文件不是 UTF-8 文本，请下载后查看。"
        return result
    if "\x00" in text:
        result["detail"] = "文件包含二进制内容，请下载后查看。"
        return result
    return {
        **result,
        "kind": "text",
        "text": text,
        "truncated": truncated,
        "detail": "当前磁盘内容；可能与任务执行时不同。HTML 和脚本按纯文本显示，不执行。",
    }


def summary(store, tid):
    task = store.task(tid)
    artifacts = recorded_artifacts(store, tid)
    for item in artifacts:
        try:
            path = artifact_path(store, tid, item["path"])
            item.update(available=True, size=path.stat().st_size)
        except (OSError, ValueError, PermissionError):
            item.update(available=False, size=None)
    rows = store.rows(
        "SELECT provider,input_tokens,output_tokens,estimated,cost FROM usage WHERE task_id=?",
        (tid,),
    )
    usage = {
        "requests": len(rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "estimated": any(r["estimated"] for r in rows),
        "known_cost": sum(r["cost"] for r in rows if r["cost"] is not None),
        "unknown_cost_requests": sum(r["cost"] is None for r in rows),
    }
    return {
        "version": 1,
        "task_id": tid,
        "state": task["state"],
        "revision": task["revision"],
        "goal": task["spec"]["goal"],
        "workspace": task["spec"]["workspace"],
        "planned_deliverables": task["spec"]["deliverables"],
        "acceptance": task["spec"]["acceptance"],
        "verification": task["verification"],
        "artifacts": artifacts,
        "usage": usage,
        "calls": store.rows(
            "SELECT id,tool,status,created FROM calls WHERE task_id=? ORDER BY created,rowid",
            (tid,),
        ),
        "limitations": [
            "产物列表仅包含成功工具调用记录的文件；终端自行生成的文件可能未登记。",
            "预览和下载读取当前文件，不代表执行时的快照。",
            "文字验收条件需要人工确认；工具成功不等于用户已验收。",
        ],
    }
