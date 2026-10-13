import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.code_search import FileSearch, SymbolSearch, search_files, search_symbols
from services.agent.engine import Engine
from services.agent.policy import PolicyEngine
from services.agent.store import Store
from tests.test_core import make_task, wait_state
from tests.test_execution import create
from tests.test_tool_errors import SequenceProvider, action


def test_research_auto_approval_follows_mode(tmp_path):
    store = Store(tmp_path / "db")
    task = make_task(store, tmp_path)
    task["spec"]["tools"] += ["web.fetch", "web.search"]
    policy = PolicyEngine(store)
    for name, args in [
        ("web.fetch", {"url": "https://example.com"}),
        ("web.search", {"query": "rendering"}),
    ]:
        assert policy.allowed(task, name, args, "call")
        task["spec"]["mode"] = "ask"
        assert not policy.allowed(task, name, args, "call")
        task["spec"]["mode"] = "workspace"


def test_parallel_reads_overlap_but_write_is_a_barrier(tmp_path):
    store = Store(tmp_path / "db")
    task = make_task(store, tmp_path)
    for index in range(4):
        (tmp_path / f"{index}.txt").write_text(str(index))
    engine = Engine(store)

    async def run():
        original = engine.tools.execute
        active = 0
        peak = 0
        ready = asyncio.Event()
        seen = []

        async def execute(task, name, args, emit):
            nonlocal active, peak
            if name == "files.read" and args["path"] != "after.txt":
                active += 1
                peak = max(peak, active)
                if active == 4:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 2)
                try:
                    return await original(task, name, args, emit)
                finally:
                    active -= 1
            assert active == 0
            return await original(task, name, args, emit)

        engine.tools.execute = execute

        async def emit(kind, payload):
            store.event(task["id"], kind, payload)

        calls = [dict(id=str(i), **action("files.read", path=f"{i}.txt")) for i in range(4)]
        calls += [
            dict(id="w", **action("files.write", path="after.txt", content="after reads")),
            dict(id="r", **action("files.read", path="after.txt")),
        ]
        async for call, cid, result in engine.execute_batch(task, calls, emit, "test", None, None):
            assert result["status"] == "succeeded", result
            seen.append(call["id"])
        assert peak == 4
        assert seen == ["0", "1", "2", "3", "w", "r"]

    asyncio.run(run())


def test_regex_glob_context_paging_and_incremental_symbols(tmp_path):
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "render.py"
    source.write_text(
        "class Renderer:\n    def shade(self):\n        return 1\n\ndef Render():\n    return 2\n"
    )
    (tmp_path / "skip.py").write_text("def ignored(): pass")
    args = FileSearch(
        query=r"def\s+\w+", regex=True, glob="src/**/*.py", max_results=1
    ).model_dump()
    first = search_files(tmp_path, args)
    assert first["output"][0]["line"] == 2
    assert first["output"][0]["context"][0]["text"] == "class Renderer:"
    assert first["truncated"] and first["next_offset"] == 1
    second = search_files(tmp_path, {**args, "offset": 1})
    assert second["output"][0]["line"] == 5
    query = SymbolSearch(query="shade").model_dump()
    one = search_symbols(tmp_path, query)
    assert one["output"][0]["qualified_name"] == "Renderer.shade"
    assert one["output"][0]["kind"] == "method"
    assert search_symbols(tmp_path, query)["cache_hits"] >= 1
    source.write_text("class Renderer:\n    def illuminate(self):\n        return 4\n")
    assert not search_symbols(tmp_path, query)["output"]
    assert search_symbols(tmp_path, {**query, "query": "illuminate"})["output"]
    source.unlink()
    assert not search_symbols(tmp_path, {**query, "query": "illuminate"})["output"]


def test_subagent_reads_twenty_files_without_filling_parent_context(tmp_path):
    main = SequenceProvider([[action("agent.delegate", objective="Find rendering modules")]])
    child = SequenceProvider([[action("files.read", path=f"module_{i}.py") for i in range(20)]])
    app = create_app(tmp_path / "data", "t")
    created = iter([main, child])
    app.state.engine.provider = lambda _: next(created)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client)
        root = Path(task["spec"]["workspace"])
        for index in range(20):
            (root / f"module_{index}.py").write_text(
                f"# PRIVATE_DETAIL_{index}\ndef shade_{index}(): return {index}\n"
            )
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        assert (
            wait_state(client, tid, {"awaiting_feedback", "waiting_for_user", "failed"})["state"]
            == "awaiting_feedback"
        )
        assert "PRIVATE_DETAIL_19" in str(child.requests[-1])
        assert "PRIVATE_DETAIL_" not in str(main.requests[-1])
        history = app.state.engine.history(tid)
        assert len(history) == 1 and history[0]["tool"] == "agent.delegate"
        result = json.loads(history[0]["result"])
        assert result["tool_calls"] == 20
        assert result["evidence"] and len(result["output"]) <= 1600
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert len(calls) == 21  # child evidence remains inspectable, outside parent messages
        assert all(call["status"] == "succeeded" for call in calls)
        assert len(app.state.engine.store.rows("SELECT * FROM usage WHERE task_id=?", (tid,))) == 4


def test_parallel_cancellation_joins_inflight_reads(tmp_path):
    store = Store(tmp_path / "db")
    task = make_task(store, tmp_path)
    engine = Engine(store)

    async def run():
        entered = 0
        cancelled = 0
        ready = asyncio.Event()

        async def blocked(*args):
            nonlocal entered, cancelled
            entered += 1
            if entered == 4:
                ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled += 1

        engine.tools.execute = blocked

        async def emit(kind, payload):
            store.event(task["id"], kind, payload)

        async def consume():
            calls = [dict(id=str(i), **action("files.read", path=f"{i}.txt")) for i in range(4)]
            async for _ in engine.execute_batch(task, calls, emit, "cancel", None, None):
                pass

        job = asyncio.create_task(consume())
        await asyncio.wait_for(ready.wait(), 2)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        assert cancelled == 4
        assert all(row["status"] == "interrupted" for row in engine.history(task["id"]))

    asyncio.run(run())


def test_regex_error_is_returned_and_model_can_fix_query(tmp_path):
    provider = SequenceProvider(
        [
            [action("files.search", query="(", regex=True)],
            [action("files.search", query="target", glob="**/*.py")],
        ]
    )
    app = create_app(tmp_path / "data", "t")
    app.state.engine.provider = lambda _: provider
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client)
        Path(task["spec"]["workspace"], "target.py").write_text("target = 1\n")
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        assert (
            wait_state(client, tid, {"awaiting_feedback", "failed", "waiting_for_user"})["state"]
            == "awaiting_feedback"
        )
        feedback = next(m for m in provider.requests[1] if m["role"] == "tool")
        assert "error_info" in json.loads(feedback["content"])
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert calls[1]["result"]["output"][0]["path"] == "target.py"


def test_native_protocol_subagent_handoff_contains_summary_not_raw_reads(tmp_path):
    import httpx

    from services.agent.models import ProviderConfig
    from services.agent.providers import OpenAICompatible

    counts = {"main": 0, "child": 0}

    def handler(request):
        body = json.loads(request.content)
        child = "独立上下文" in body["messages"][0]["content"]
        branch = "child" if child else "main"
        counts[branch] += 1
        if counts[branch] == 1:
            name = "files__read" if child else "agent__delegate"
            args = {"path": "render.py"} if child else {"objective": "Locate renderer"}
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": branch + "-tool",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            }
        else:
            encoded = json.dumps(body["messages"])
            assert ("RAW_CHILD_SOURCE" in encoded) == child
            if not child:
                assert "render.py:1" in encoded
            message = {"role": "assistant", "content": "render.py:1 contains the renderer."}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    app = create_app(tmp_path / "data", "t")
    config = ProviderConfig(
        id="fixture", name="fixture", model="fixture", tools=True, streaming=False
    )
    app.state.engine.provider = lambda _: OpenAICompatible(config, httpx.MockTransport(handler))
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client, provider="fixture")
        Path(task["spec"]["workspace"], "render.py").write_text(
            "# RAW_CHILD_SOURCE\ndef render(): pass\n"
        )
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        stopped = wait_state(client, tid, {"awaiting_feedback", "waiting_for_user", "failed"})
        assert stopped["state"] == "awaiting_feedback", stopped
        assert counts == {"main": 2, "child": 2}
