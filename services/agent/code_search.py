"""Bounded code search and an incremental, workspace-scoped symbol index."""

import ast
import fnmatch
import os
import re
import threading
from pathlib import Path
from typing import Literal

import regex
from pydantic import Field

from .models import Strict
from .policy import inside
from .workspace import SKIP


class SearchScope(Strict):
    path: str = "."
    glob: str = "**/*"
    exclude: list[str] = Field(default_factory=list, max_length=20)
    max_files: int = Field(default=5000, ge=1, le=20000)
    max_results: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=100000)


class FileSearch(SearchScope):
    query: str = Field(min_length=1, max_length=1000)
    regex: bool = False
    case_sensitive: bool = True
    context_lines: int = Field(default=2, ge=0, le=5)


class SymbolSearch(SearchScope):
    query: str = Field(default="", max_length=200)
    kind: Literal["any", "class", "function", "method", "interface", "type"] = "any"


def matches(path, pattern):
    from functools import lru_cache

    parts = path.replace("\\", "/").split("/")
    patterns = pattern.replace("\\", "/").split("/")

    @lru_cache(None)
    def match(i, j):
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)

    return match(0, 0)


def candidates(root, args):
    folder = inside(root, args["path"])
    if folder.is_file():
        yield folder
        return
    for current, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP | {"data"} and not Path(current, d).is_symlink()
        )
        for filename in sorted(files):
            candidate = Path(current, filename)
            if candidate.is_symlink():
                continue
            candidate = inside(root, str(candidate))
            relative = candidate.relative_to(Path(root).resolve()).as_posix()
            if matches(relative, args["glob"]) and not any(
                matches(relative, p) for p in args["exclude"]
            ):
                yield candidate


def search_files(root, args):
    pattern = args["query"] if args["regex"] else re.escape(args["query"])
    compiled = regex.compile(pattern, 0 if args["case_sensitive"] else regex.IGNORECASE)
    output, scanned, found, truncated = [], 0, 0, False
    for path in candidates(root, args):
        if scanned >= args["max_files"]:
            truncated = True
            break
        scanned += 1
        try:
            if path.stat().st_size > 4_000_000:
                continue
            content = path.read_text("utf-8-sig")
            if "\0" in content:
                continue
        except (OSError, UnicodeError):
            continue
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if not compiled.search(line, timeout=0.1):
                continue
            found += 1
            if found <= args["offset"]:
                continue
            if len(output) >= args["max_results"]:
                truncated = True
                break
            radius = args["context_lines"]
            output.append(
                {
                    "path": path.relative_to(Path(root).resolve()).as_posix(),
                    "line": index + 1,
                    "text": line[:1000],
                    "context": [
                        {"line": n + 1, "text": lines[n][:1000]}
                        for n in range(max(0, index - radius), min(len(lines), index + radius + 1))
                    ],
                }
            )
        if truncated:
            break
    return {
        "output": output,
        "scanned_files": scanned,
        "truncated": truncated,
        "next_offset": args["offset"] + len(output) if truncated and output else None,
        "verification": "逐行文本匹配；跳过二进制、依赖目录及超过 4 MB 的文件。路径和行号可用于后续精读。",
    }


_index = {}
_lock = threading.Lock()


def parse_symbols(path, text):
    if path.suffix == ".py":
        tree = ast.parse(text)
        output = []

        def visit(node, parents=()):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = (
                        "class"
                        if isinstance(child, ast.ClassDef)
                        else "method" if isinstance(node, ast.ClassDef) else "function"
                    )
                    output.append(
                        {
                            "name": child.name,
                            "qualified_name": ".".join((*parents, child.name)),
                            "kind": kind,
                            "line": child.lineno,
                            "end_line": child.end_lineno,
                            "parser": "python_ast",
                        }
                    )
                    visit(child, (*parents, child.name))
                else:
                    visit(child, parents)

        visit(tree)
        return output
    if path.suffix.lower() not in {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".cpp",
        ".cc",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".java",
    }:
        return []
    output = []
    patterns = [
        (r"\b(class|struct|interface|type)\s+([A-Za-z_$][\w$]*)", None),
        (r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", "function"),
        (
            r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>",
            "function",
        ),
        (r"^\s*(?:[\w:*&<>]+\s+)+([A-Za-z_][\w:]*)\s*\([^;]*\)\s*(?:const\s*)?\{", "function"),
    ]
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("//", "/*", "*")):
            continue
        for pattern, kind in patterns:
            match = re.search(pattern, line)
            if match:
                name = match.group(1 if kind else 2)
                output.append(
                    {
                        "name": name,
                        "qualified_name": name,
                        "kind": kind or {"struct": "class"}.get(match.group(1), match.group(1)),
                        "line": number,
                        "parser": "lexical_approximation",
                    }
                )
                break
    return output


def search_symbols(root, args):
    output, scanned, rebuilt, hits, total = [], 0, 0, 0, 0
    truncated = False
    for path in candidates(root, args):
        if path.suffix.lower() not in {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".cpp",
            ".cc",
            ".c",
            ".h",
            ".hpp",
            ".cs",
            ".java",
        }:
            continue
        if scanned >= args["max_files"]:
            truncated = True
            break
        scanned += 1
        try:
            stat = path.stat()
            if stat.st_size > 4_000_000:
                continue
            key, version = str(path), (stat.st_mtime_ns, stat.st_size)
            with _lock:
                cached = _index.get(key)
            if cached and cached[0] == version:
                symbols = cached[1]
                hits += 1
            else:
                symbols = parse_symbols(path, path.read_text("utf-8-sig"))
                with _lock:
                    if len(_index) >= 20000:
                        _index.clear()
                    _index[key] = (version, symbols)
                rebuilt += 1
        except (OSError, UnicodeError, SyntaxError):
            continue
        for item in symbols:
            if args["query"].casefold() not in item["qualified_name"].casefold() or args[
                "kind"
            ] not in ("any", item["kind"]):
                continue
            total += 1
            if total <= args["offset"]:
                continue
            if len(output) >= args["max_results"]:
                truncated = True
                break
            output.append({**item, "path": path.relative_to(Path(root).resolve()).as_posix()})
        if truncated:
            break
    return {
        "output": output,
        "scanned_files": scanned,
        "rebuilt_files": rebuilt,
        "cache_hits": hits,
        "truncated": truncated,
        "next_offset": args["offset"] + len(output) if truncated and output else None,
        "verification": "Python 使用 AST；其他语言是声明的词法定位，不是跨文件类型/引用解析。索引在进程内按文件版本更新，删除文件不会出现在查询结果。",
    }
