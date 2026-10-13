"""Workspace orientation and small, reviewable source edits."""

import difflib
import hashlib
import itertools
import json
import os
import platform
import shutil
import tempfile
from pathlib import Path

from pydantic import Field

from .models import Strict
from .policy import inside
from .store import uid

SKIP = {
    ".git",
    "node_modules",
    ".runtime",
    ".venv",
    "venv",
    "__pycache__",
    ".agent-browser-profile",
    "dist",
    "build",
}


class DirectoryList(Strict):
    path: str = "."
    depth: int = Field(default=1, ge=1, le=6)
    max_entries: int = Field(default=300, ge=1, le=1000)


class WorkspaceInspect(DirectoryList):
    depth: int = Field(default=3, ge=1, le=6)


class Replacement(Strict):
    old: str = Field(min_length=1, max_length=100000)
    new: str = Field(max_length=200000)
    expected_matches: int = Field(default=1, ge=1, le=100)


class FileEdit(Strict):
    path: str
    expected_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    edits: list[Replacement] = Field(min_length=1, max_length=30)


def directory_listing(root, args):
    folder = inside(root, args["path"])
    if not folder.is_dir():
        raise ValueError("列目录需要目录路径")
    entries = []
    truncated = False
    pending = [(folder, 1)]
    while pending:
        current, depth = pending.pop(0)
        # Bound enumeration as well as the returned result (large generated trees).
        remaining = args["max_entries"] - len(entries)
        with os.scandir(current) as scan:
            children = list(itertools.islice(scan, remaining + 1))
        if len(children) > remaining:
            truncated = True
            children = children[:remaining]
        for child in sorted(children, key=lambda x: x.name.casefold()):
            path = Path(child.path)
            relative = path.relative_to(Path(root).resolve()).as_posix()
            linked = child.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
            directory = child.is_dir(follow_symlinks=False)
            entry = {"name": child.name, "path": relative, "directory": directory}
            if linked:
                entry["link"] = True
            if directory and child.name in SKIP:
                entry["excluded"] = True
            entries.append(entry)
            if directory and not linked and child.name not in SKIP and depth < args["depth"]:
                pending.append((inside(root, relative), depth + 1))
        if len(entries) >= args["max_entries"]:
            truncated = truncated or bool(pending)
            break
    return {
        "output": entries,
        "truncated": truncated,
        "depth": args["depth"],
        "excluded_directories": sorted(SKIP),
    }


def inspect_workspace(root, args):
    listing = directory_listing(root, args)
    projects = []
    for entry in listing["output"]:
        if entry["directory"] or entry.get("link"):
            continue
        name, path = entry["name"], entry["path"]
        kind = next(
            (
                kind
                for suffix, kind in (
                    ("package.json", "node"),
                    ("pyproject.toml", "python"),
                    ("requirements.txt", "python"),
                    ("CMakeLists.txt", "cmake"),
                    ("Cargo.toml", "rust"),
                    ("go.mod", "go"),
                    (".sln", "visual_studio"),
                    (".vcxproj", "visual_studio"),
                )
                if name == suffix or (suffix.startswith(".") and name.endswith(suffix))
            ),
            None,
        )
        if not kind:
            continue
        item = {"kind": kind, "path": path}
        if name == "package.json":
            try:
                with inside(root, path).open("rb") as f:
                    raw = f.read(65537)
                if len(raw) <= 65536:
                    config = json.loads(raw)
                    scripts = config.get("scripts", {})
                    if isinstance(scripts, dict):
                        item["scripts"] = {
                            str(k)[:100]: str(v)[:500] for k, v in list(scripts.items())[:20]
                        }
            except (OSError, ValueError, AttributeError):
                item["note"] = "配置无法解析；请读取文件确认"
        projects.append(item)
    available = {
        name: path
        for name in ("python", "node", "git", "cmake", "cl", "g++", "cargo", "go")
        if (path := shutil.which(name))
    }
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    return {
        **listing,
        "projects": projects,
        "environment": {
            "os": platform.system(),
            "architecture": platform.machine(),
            "executables_on_path": available,
            "vswhere": str(vswhere) if vswhere.is_file() else None,
        },
        "guidance": "配置和命令仅是发现结果，未执行。先读取相关源码及项目说明，使用现有构建系统；Windows 的 cl 不在 PATH 不代表没装 VS，可用 vswhere 查询安装。用户指定 VS 时不要擅自改用其他编译器。",
    }


def edit_file(root, args, store=None, task_id=None):
    path = inside(root, args["path"])
    with path.open("rb") as f:
        original = f.read(8_000_001)
    if len(original) > 8_000_000 or b"\0" in original:
        raise ValueError("局部编辑支持最多 8 MB 的 UTF-8 文本，请选择源码文件")
    if hashlib.sha256(original).hexdigest() != args["expected_sha256"].lower():
        raise ValueError("文件发生变化，请读取当前文件和 sha256 后重新编辑")
    before = original.decode("utf-8")
    after = before
    crlf = "\r\n" in before and "\n" not in before.replace("\r\n", "")
    for i, edit in enumerate(args["edits"]):
        old, new = edit["old"], edit["new"]
        if crlf:
            old = old.replace("\r\n", "\n").replace("\n", "\r\n")
            new = new.replace("\r\n", "\n").replace("\n", "\r\n")
        matches = after.count(old)
        if matches != edit["expected_matches"]:
            raise ValueError(
                f"第 {i + 1} 处编辑匹配 {matches} 次，预期 {edit['expected_matches']} 次；读取相关段落并提供更具体的 old 文本。文件未修改。"
            )
        after = after.replace(old, new)
    encoded = after.encode("utf-8")
    if len(encoded) > 8_000_000:
        raise ValueError("编辑后的文件超过 8 MB，请拆分源码")
    if encoded == original:
        return {
            "output": "内容无变化",
            "sha256": hashlib.sha256(original).hexdigest(),
            "artifacts": [],
        }
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".agent-edit-", delete=False) as f:
            temp = Path(f.name)
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(path, temp)
        if inside(root, args["path"]) != path or path.read_bytes() != original:
            raise ValueError("文件发生变化，未覆盖并发修改")
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    digest = hashlib.sha256(encoded).hexdigest()
    change_id = None
    if store is not None:
        change_id = uid()
        store.run(
            "INSERT INTO changes VALUES(?,?,?,?,?,0)",
            (change_id, task_id, str(path), before, digest),
        )
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=args["path"],
            tofile=args["path"],
        )
    )
    return {
        "output": f"已完成 {len(args['edits'])} 处局部编辑",
        "sha256": digest,
        "change_id": change_id,
        "artifacts": [path.relative_to(Path(root).resolve()).as_posix()],
        "diff": diff[:24000],
        "diff_truncated": len(diff) > 24000,
    }
