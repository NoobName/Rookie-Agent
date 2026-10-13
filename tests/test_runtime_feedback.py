import os
import sys

import pytest

from services.agent.policy import PolicyEngine
from services.agent.store import Store
from services.agent.tools import Tools
from tests.test_core import make_task


def test_workspace_terminal_grant_persists_and_revokes(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    store = Store(tmp_path / "data")
    policy = PolicyEngine(store)
    task = make_task(store, root)
    args = {"argv": ["python", "a.py"]}
    assert not policy.allowed(task, "terminal.run", args, "a")
    grant = policy.grant_rule(task, "terminal.run", args, "workspace_terminal", 1)
    policy = PolicyEngine(Store(tmp_path / "data"))
    next_task = make_task(store, root)
    assert policy.allowed(next_task, "terminal.run", {"argv": ["python", "b.py"]}, "b")
    assert not policy.allowed(make_task(store, other), "terminal.run", args, "c")
    with pytest.raises(ValueError):
        policy.grant_rule(task, "files.write", {}, "workspace_terminal", 1)
    with pytest.raises(PermissionError):
        policy.allowed(task, "terminal.run", {"cwd": str(other)}, "d")
    store.run("UPDATE permission_rules SET revoked=1 WHERE id=?", (grant,))
    assert not policy.allowed(next_task, "terminal.run", args, "e")


async def test_batch_newlines_stdin_and_output_limit(tmp_path):
    tools = Tools()
    task = {"id": "t", "spec": {"workspace": str(tmp_path)}}

    async def emit(*args):
        pass

    await tools.execute(
        task,
        "files.write",
        {"path": "test.bat", "content": "@echo off\nrem 中文注释\necho OK\n"},
        emit,
    )
    raw = (tmp_path / "test.bat").read_bytes()
    assert raw.count(b"\r\n") == 3
    if os.name == "nt":
        result = await tools.command("t", ["cmd", "/c", "test.bat"], str(tmp_path), 5, emit)
        assert result["status"] == "succeeded" and "OK" in result["stdout"]
    result = await tools.command(
        "t",
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
        str(tmp_path),
        5,
        emit,
    )
    assert result["stdout"].strip() == "''"
    result = await tools.command(
        "t",
        [sys.executable, "-c", 'import sys; sys.stdout.write("x"*2100000)'],
        str(tmp_path),
        5,
        emit,
    )
    assert result["status"] == "failed" and "2 MB" in result["error"]
    assert len(result["stdout"]) <= 30000


@pytest.mark.skipif(os.name != "nt", reason="Windows codepage")
async def test_windows_auto_decode(tmp_path):
    import ctypes

    codec = "cp" + str(ctypes.windll.kernel32.GetACP())

    async def emit(*args):
        pass

    result = await Tools().command(
        "t",
        [sys.executable, "-c", f'import sys;sys.stdout.buffer.write("中文错误".encode({codec!r}))'],
        str(tmp_path),
        5,
        emit,
    )
    assert result["stdout"] == "中文错误"


async def test_large_utf8_pages_and_binary_metadata(tmp_path):
    tools = Tools()
    task = {"id": "t", "spec": {"workspace": str(tmp_path)}}

    async def emit(*args):
        pass

    content = "中文 render\n" * 110000
    (tmp_path / "large.txt").write_bytes(content.encode())
    offset = 0
    pieces = []
    while True:
        result = await tools.execute(
            task, "files.read", {"path": "large.txt", "offset": offset, "max_bytes": 65536}, emit
        )
        assert result["status"] == "succeeded" and not result["binary"]
        pieces.append(result["output"])
        if not result["truncated"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert "".join(pieces) == content
    import hashlib

    assert result["sha256"] == hashlib.sha256(content.encode()).hexdigest()
    (tmp_path / "render.bmp").write_bytes(b"BM" + b"\0" * 1100000)
    result = await tools.execute(task, "files.read", {"path": "render.bmp"}, emit)
    assert result["status"] == "succeeded" and result["binary"] and len(result["output"]) < 500


async def test_workspace_overwrite_no_prompt_but_version_protected(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    store = Store(tmp_path / "db")
    task = make_task(store, root)
    tools = Tools()
    policy = PolicyEngine(store)

    async def emit(*args):
        pass

    (root / "code.cpp").write_text("old")
    assert policy.allowed(task, "files.write", {"path": "code.cpp"}, "a")
    result = await tools.execute(task, "files.write", {"path": "code.cpp", "content": "new"}, emit)
    assert result["status"] == "failed" and (root / "code.cpp").read_text() == "old"
    read = await tools.execute(task, "files.read", {"path": "code.cpp"}, emit)
    result = await tools.execute(
        task,
        "files.write",
        {"path": "code.cpp", "content": "new", "expected_sha256": read["sha256"]},
        emit,
    )
    assert result["status"] == "succeeded"
    task["spec"]["mode"] = "ask"
    assert not policy.allowed(task, "files.write", {"path": "code.cpp"}, "b")
    with pytest.raises(PermissionError):
        policy.allowed(task, "files.write", {"path": "../escape"}, "c")
