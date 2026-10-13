import asyncio
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import keyring
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .accounting import UsageLimits, limits, price, totals
from .attachments import context_parts
from .context import budget, conversation_context
from .engine import SYSTEM, Engine
from .evaluations import create_evaluation
from .evaluations import history as evaluation_history
from .mcp_registry import MCPServer
from .models import Approval, Message, ProviderConfig, RecoveryDecision, Steering, Strict, TaskSpec
from .policy import inside
from .provider_errors import explain
from .results import artifact_path, preview, summary
from .scheduler import Schedule, Scheduler
from .skills import Skill, catalog
from .store import Store, dump, uid
from .tools import SCHEMAS

ROOT = Path(os.getenv("AGENT_RESOURCE_ROOT", Path(__file__).resolve().parents[2]))


def create_app(data_dir=None, token=None):
    data = Path(data_dir or os.getenv("AGENT_DATA", ROOT / "data")).resolve()
    store = Store(data)
    token_path = data / "client.token"
    if token is None:
        if not token_path.exists():
            token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        token = token_path.read_text(encoding="utf-8").strip()
    # Separate domain/key from API authentication. This random per-start key is never
    # accepted as a Bearer credential; a caller-chosen challenge cannot test API tokens.
    discovery_key = secrets.token_hex(32)
    (data / "discovery.key").write_text(discovery_key, encoding="utf-8")
    engine = Engine(store)
    inflight = {}
    scheduler = Scheduler(store, engine)

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        engine.start()
        scheduler.start()
        yield
        await scheduler.close()
        await engine.close()

    app = FastAPI(
        title="Local Agent Workbench",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.engine = engine
    port = int(os.getenv("AGENT_PORT", "8765"))
    origins = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }

    @app.middleware("http")
    async def security(request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"detail": "Origin 被拒绝"}, status_code=403)
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "Host 被拒绝"}, status_code=403)
        if not engine.accepting and request.method not in ("GET", "OPTIONS"):
            return JSONResponse({"detail": "后端正在关闭"}, status_code=503)
        if request.method == "OPTIONS":
            response = JSONResponse({})
        elif request.url.path.startswith("/api") and not secrets.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + token
        ):
            return JSONResponse(
                {"detail": "需要客户端认证，请使用启动器链接或输入本机令牌"}, status_code=401
            )
        else:
            try:
                response = await call_next(request)
            except (ValueError, KeyError, PermissionError) as exc:
                response = JSONResponse({"detail": str(exc)}, status_code=400)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization,Content-Type,Last-Event-ID"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        if request.url.path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' http://127.0.0.1:{port}; img-src 'self' blob: data:; frame-ancestors 'none'"
        )
        return response

    @app.get("/health")
    async def health():
        # Public liveness only: no token-dependent output, including for legacy nonce queries.
        return {"ok": True, "app": "local-agent", "version": "0.8.1"}

    @app.get("/discovery")
    async def discovery(nonce: str):
        import hashlib
        import hmac
        import re

        if not re.fullmatch("[a-f0-9]{32}", nonce):
            raise ValueError("发现请求 nonce 无效")
        directory = str(data)
        return {
            "app": "local-agent",
            "data_dir": directory,
            "proof": hmac.new(
                discovery_key.encode(), (nonce + "\n" + directory).encode(), hashlib.sha256
            ).hexdigest(),
        }

    @app.get("/api/notifications")
    async def notifications(after: int = 0, latest: bool = False):
        cursor = store.one("SELECT COALESCE(MAX(id),0) n FROM events WHERE type='notification'")[
            "n"
        ]
        rows = (
            []
            if latest
            else store.rows(
                "SELECT * FROM events WHERE type='notification' AND id>? ORDER BY id LIMIT 100",
                (after,),
            )
        )
        return {
            "cursor": cursor if latest else (rows[-1]["id"] if rows else after),
            "events": [{**r, "payload": json.loads(r["payload"])} for r in rows],
        }

    @app.get("/api/usage")
    async def usage_summary():
        return {
            "total": totals(store),
            "limits": limits(store).model_dump(),
            "providers": store.rows(
                "SELECT provider,COUNT(*) requests,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens,SUM(cost) known_cost,SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) unknown_cost_requests FROM usage GROUP BY provider"
            ),
            "recent": store.rows(
                "SELECT u.*,m.cached_input_tokens,m.latency FROM usage u LEFT JOIN usage_meta m ON m.usage_id=u.id ORDER BY u.created DESC LIMIT 100"
            ),
        }

    @app.get("/api/evaluations")
    async def evaluations():
        return evaluation_history(store)

    @app.post("/api/evaluations")
    async def evaluation(body: dict):
        return create_evaluation(store, body.get("provider", ""), body.get("suite", ""))

    @app.put("/api/usage/limits")
    async def usage_limits(body: UsageLimits):
        store.run(
            "INSERT OR REPLACE INTO settings VALUES(?,?)", ("usage_limits", body.model_dump_json())
        )
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown():
        if engine.enqueued or (engine.active and not engine.active.done()):
            raise ValueError("有执行中或排队任务，请先暂停或取消")
        callback = getattr(app.state, "shutdown", None)
        if callback is None:
            raise ValueError("当前启动方式不支持关闭，请在启动终端按 Ctrl+C")
        engine.accepting = False
        asyncio.get_running_loop().call_later(0.2, callback)
        return {"ok": True}

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {
            "sessions": store.rows(
                "SELECT s.*,p.project_id FROM sessions s LEFT JOIN session_projects p ON p.session_id=s.id ORDER BY s.created DESC"
            ),
            "projects": store.rows("SELECT * FROM projects ORDER BY created DESC"),
            "tasks": [
                store.task(t["id"])
                for t in store.rows("SELECT id FROM tasks ORDER BY created DESC")
            ],
            "providers": [
                {
                    "id": "scripted",
                    "name": "Scripted · 确定性演示",
                    "model": "fixture",
                    "verified": {"status": "本地演示，不是真实模型"},
                }
            ]
            + [json.loads(x["config"]) for x in store.rows("SELECT config FROM providers")],
            "workspace": str((data / "workspaces").resolve()),
            "tools": [n for n in SCHEMAS if n != "checks.run"],
            "desktop": {
                "stopped": engine.tools.desktop.stopped,
                "target": engine.tools.desktop.target,
            },
            "capabilities": {
                "search": "未配置搜索服务",
                "desktop": "需可选依赖及手动启用",
                "collaboration": "可选只读串行咨询，真实模型待测",
                "email": "默认禁用",
                "browser": "独立 Chromium，需安装浏览器",
            },
        }

    @app.post("/api/sessions")
    async def create_session(body: dict):
        project = body.get("project_id")
        if project:
            store.one("SELECT id FROM projects WHERE id=?", (project,))
        ident = uid()
        store.run(
            "INSERT INTO sessions VALUES(?,?,?)",
            (ident, str(body.get("title", "新会话"))[:120], time.time()),
        )
        if project:
            store.run("INSERT INTO session_projects VALUES(?,?)", (ident, project))
        return {"id": ident}

    @app.post("/api/projects")
    async def create_project(body: dict):
        name = str(body.get("name", "")).strip()
        if not name or len(name) > 120:
            raise ValueError("项目名称须为 1–120 个字符")
        workspace = Path(str(body.get("workspace", ""))).expanduser()
        if (
            not str(body.get("workspace", "")).strip()
            or not workspace.is_absolute()
            or not workspace.is_dir()
        ):
            raise ValueError("请选择已存在的绝对工作区目录")
        ident = uid()
        store.run(
            "INSERT INTO projects VALUES(?,?,?,?)",
            (ident, name, str(workspace.resolve()), time.time()),
        )
        return store.one("SELECT * FROM projects WHERE id=?", (ident,))

    @app.get("/api/directories")
    async def directories(path: str = ""):
        root = Path(path).expanduser() if path else Path.home()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("目录不存在，请输入本机绝对路径")
        root = root.resolve()
        children = []
        try:
            for item in root.iterdir():
                try:
                    if item.is_dir() and not item.name.startswith("."):
                        children.append({"name": item.name, "path": str(item)})
                except OSError:
                    pass
        except OSError:
            raise ValueError("无法读取此目录")
        drives = (
            [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").is_dir()]
            if os.name == "nt"
            else ["/"]
        )
        return {
            "path": str(root),
            "parent": str(root.parent),
            "directories": sorted(children, key=lambda x: x["name"].casefold())[:300],
            "drives": drives,
        }

    @app.get("/api/sessions/{sid}/messages")
    async def messages(sid: str):
        return store.rows("SELECT * FROM messages WHERE session_id=? ORDER BY created", (sid,))

    @app.post("/api/sessions/{sid}/chat")
    async def chat(sid: str, body: Message):
        if body.execute:
            store.one("SELECT id FROM sessions WHERE id=?", (sid,))
            previous = [
                store.task(r["id"])
                for r in store.rows(
                    "SELECT id FROM tasks WHERE session_id=? ORDER BY created DESC", (sid,)
                )
            ]
            if any(
                t["id"] in engine.enqueued
                or t["state"] in ("running", "verifying", "awaiting_approval")
                for t in previous
            ):
                raise ValueError("当前对话仍在执行，请先暂停或等待完成")
            if any(t["needs_recovery"] for t in previous):
                raise ValueError("请先审查此对话中的中断操作，再发送新请求")
            provider = engine.provider(body.provider)
            if body.provider != "scripted" and not provider.config.tools:
                raise ValueError("请在模型设置中启用原生工具能力后使用执行对话")
            if body.collaboration and not body.collaboration_mapping:
                raise ValueError("请选择协作审阅模型")
            for pid in body.collaboration_mapping.values():
                engine.provider(pid)
            project = store.rows(
                "SELECT p.workspace FROM projects p JOIN session_projects s ON s.project_id=p.id WHERE s.session_id=?",
                (sid,),
            )
            workspace = (
                body.workspace
                or (project[0]["workspace"] if project else "")
                or (previous[0]["spec"]["workspace"] if previous else "")
            )
            if not workspace:
                directory = data / "workspaces" / sid
                directory.mkdir(parents=True, exist_ok=True)
                workspace = str(directory)
            directory = Path(workspace).resolve(strict=True)
            if not directory.is_dir():
                raise ValueError("工作区不是目录")
            for ident in body.attachments:
                store.one("SELECT id FROM attachments WHERE id=?", (ident,))
            history = store.rows(
                "SELECT id,role,content FROM messages WHERE session_id=? ORDER BY created,rowid",
                (sid,),
            )
            history_limit = min(
                12000, budget(getattr(provider, "config", None))["input_limit"] // 4
            )
            spec = TaskSpec(
                conversational=True,
                goal=body.content[:20000],
                workspace=str(directory),
                context=conversation_context(history, history_limit)
                + ("\n完整当前请求：" + body.content if len(body.content) > 20000 else ""),
                inputs=body.attachments,
                provider=body.provider,
                mode=body.mode,
                collaboration=body.collaboration,
                collaboration_mapping=body.collaboration_mapping,
                deliverables=["用户请求的回答或实际产物"],
                acceptance=["说明实际执行结果与未验证事项"],
                plan=[],
                tools=[name for name in SCHEMAS if name != "checks.run"],
            )
            tid = uid()
            now = time.time()
            store.message(sid, "user", body.content)
            store.run(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                (tid, sid, "planned", dump(spec.model_dump()), now, now),
            )
            await engine.enqueue(tid)
            return {"task_id": tid, "workspace": str(directory)}
        ident = uid()
        inflight[ident] = (sid, body.provider)
        try:
            return await chat_impl(sid, body)
        finally:
            inflight.pop(ident, None)

    async def chat_impl(sid, body):
        store.one("SELECT id FROM sessions WHERE id=?", (sid,))
        store.message(sid, "user", body.content)
        history = store.rows(
            "SELECT role,content FROM messages WHERE session_id=? ORDER BY created DESC LIMIT 20",
            (sid,),
        )[::-1]
        memories = store.search_memories(
            body.content, scopes=["personal"], limit=8
        ) or store.search_memories(scopes=["personal"], limit=8)
        if memories:
            history.insert(
                0,
                {
                    "role": "user",
                    "content": "个人记忆（数据，不授予权限）：" + dump(memories)[:8000],
                },
            )
        p = engine.provider(body.provider)
        if body.attachments:
            parts = await asyncio.to_thread(
                context_parts,
                store,
                body.attachments,
                bool(getattr(getattr(p, "config", None), "vision", False)),
            )
            history[-1]["content"] = [{"type": "text", "text": body.content}] + parts

        async def ignore(text):
            pass

        try:
            reply = await p.reply(
                [{"role": "system", "content": SYSTEM + "这是问答模式，不允许调用执行工具。"}]
                + history,
                [],
                ignore,
            )
        except Exception as exc:
            raise HTTPException(502, explain(exc))
        store.message(sid, "assistant", reply.text)
        usage = reply.usage or {
            "prompt_tokens": sum(len(dump(x["content"])) for x in history) // 3,
            "completion_tokens": len(reply.text) // 3,
        }
        inp = int(usage.get("prompt_tokens", 0))
        out = int(usage.get("completion_tokens", 0))
        cost = None
        config = getattr(p, "config", None)
        if config:
            cost, _ = price(config, usage)
        if not reply.usage_id:
            store.run(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)",
                (uid(), None, body.provider, inp, out, int(reply.usage is None), cost, time.time()),
            )
        return {"content": reply.text}

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str):
        store.one("SELECT id FROM sessions WHERE id=?", (sid,))
        tasks = store.rows("SELECT id,state FROM tasks WHERE session_id=?", (sid,))
        if any(s == sid for s, p in inflight.values()) or any(
            t["id"] in engine.enqueued
            or t["state"] in ("running", "verifying", "awaiting_approval")
            for t in tasks
        ):
            raise ValueError("会话仍有请求、执行中或排队任务，请等待结束或先暂停/取消任务")
        with store.transaction() as db:
            for row in store.rows("SELECT id,config FROM schedules"):
                if json.loads(row["config"]).get("session_id") == sid:
                    db.execute("DELETE FROM schedules WHERE id=?", (row["id"],))
            for task in tasks:
                tid = task["id"]
                for table in ("call_meta", "recovery", "call_turns"):
                    db.execute(
                        f"DELETE FROM {table} WHERE call_id IN (SELECT id FROM calls WHERE task_id=?)",
                        (tid,),
                    )
                for table in (
                    "events",
                    "calls",
                    "grants",
                    "changes",
                    "task_runtime",
                    "steering",
                    "permission_rules",
                    "model_requests",
                    "model_turns",
                    "evaluations",
                ):
                    db.execute(f"DELETE FROM {table} WHERE task_id=?", (tid,))
                db.execute("UPDATE usage SET task_id=NULL WHERE task_id=?", (tid,))
            db.execute("DELETE FROM tasks WHERE session_id=?", (sid,))
            db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            db.execute("DELETE FROM session_projects WHERE session_id=?", (sid,))
            db.execute("DELETE FROM sessions WHERE id=?", (sid,))
        return {"ok": True}

    @app.post("/api/sessions/{sid}/tasks")
    async def create_task(sid: str, spec: TaskSpec):
        store.one("SELECT id FROM sessions WHERE id=?", (sid,))
        if not spec.workspace:
            project = store.rows(
                "SELECT p.workspace FROM projects p JOIN session_projects s ON s.project_id=p.id WHERE s.session_id=?",
                (sid,),
            )
            if project:
                spec.workspace = project[0]["workspace"]
        if spec.provider == "scripted" and not spec.workspace:
            p = data / "workspaces" / uid()
            p.mkdir(parents=True)
            spec.workspace = str(p)
        workspace = Path(spec.workspace).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("工作区必须是现有目录")
        spec.workspace = str(workspace)
        ident = uid()
        now = time.time()
        with store.transaction():
            store.run(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                (ident, sid, "draft", dump(spec.model_dump()), now, now),
            )
            if not spec.acceptance or not spec.deliverables:
                store.transition(ident, "clarifying", "请补充交付物和可验证的验收条件。")
            else:
                store.transition(ident, "planned")
        return store.task(ident)

    @app.put("/api/tasks/{tid}/spec")
    async def edit_task(tid: str, spec: TaskSpec):
        with store.transaction():
            state = store.task(tid)["state"]
            if state not in (
                "draft",
                "clarifying",
                "planned",
                "paused",
                "failed",
                "awaiting_feedback",
                "waiting_for_user",
            ):
                raise ValueError("请暂停任务后修改计划")
            if not spec.acceptance or not spec.deliverables:
                raise ValueError("需要交付物和验收条件")
            spec.workspace = str(Path(spec.workspace).resolve(strict=True))
            store.run("UPDATE tasks SET spec=? WHERE id=?", (dump(spec.model_dump()), tid))
            store.revise(tid)
            if state != "planned":
                store.transition(tid, "planned", "用户更新计划；历史动作不重放")
            store.event(tid, "plan_changed", spec.model_dump())
        return store.task(tid)

    @app.post("/api/tasks/{tid}/{action}")
    async def action(tid: str, action: str, body: dict):
        if action == "start":
            await engine.enqueue(tid)
        elif action == "continue":
            task = store.task(tid)
            if task["state"] != "waiting_for_user" or task.get("stop_reason") != "step_limit":
                raise ValueError("仅回合额度耗尽的任务可直接继续；其他原因请先处理")
            if task["needs_recovery"]:
                raise ValueError("请先审查中断操作")
            store.transition(tid, "planned", "用户继续下一轮；保留计划与历史，不重放工具")
            await engine.enqueue(tid)
        elif action in ("pause", "cancel"):
            await engine.stop(tid, "paused" if action == "pause" else "cancelled")
        elif action == "accept":
            task = store.task(tid)
            runtime = store.runtime(tid)
            if (
                not task["verification"]
                or task["verification"]["status"] == "failed"
                or runtime["verified_revision"] != runtime["revision"]
            ):
                raise ValueError("当前计划尚未完成验收检查，请重新执行")
            store.transition(tid, "completed", "用户接受结果（包括人工验收条件）")
            settings = store.rows("SELECT value FROM settings WHERE key='auto_memory'")
            if settings and json.loads(settings[0]["value"]):
                spec = task["spec"]
                report = task["verification"]
                summary = (
                    "用户已接受任务："
                    + spec["goal"]
                    + "\n交付物："
                    + "；".join(spec["deliverables"])
                    + "\n机器检查："
                    + dump(report["checks"])
                    + "\n人工验收条件："
                    + "；".join(spec["acceptance"])
                )
                mid = store.memory(
                    spec["workspace"], summary[:12000], "explicit", "accepted_task:" + tid
                )
                store.event(
                    tid,
                    "memory_saved",
                    {"memory_id": mid, "detail": "按用户启用的设置保存验收摘要；未推断额外事实"},
                )
        elif action == "feedback":
            feedback = Steering.model_validate(body)
            for ident in feedback.attachments:
                store.one("SELECT id FROM attachments WHERE id=?", (ident,))
            state = store.task(tid)["state"]
            if state in ("running", "awaiting_approval", "verifying"):
                await engine.stop(tid, "paused")
                state = "paused"
            if state not in (
                "planned",
                "awaiting_feedback",
                "paused",
                "failed",
                "waiting_for_user",
            ):
                raise ValueError("当前状态不能接收任务补充")
            task = store.task(tid)
            task["spec"]["context"] += "\n用户补充：" + feedback.content
            task["spec"]["inputs"] = list(
                dict.fromkeys(task["spec"].get("inputs", []) + feedback.attachments)
            )
            store.run("UPDATE tasks SET spec=? WHERE id=?", (dump(task["spec"]), tid))
            revision = store.revise(tid)
            store.run(
                "INSERT INTO steering(task_id,content,revision,created) VALUES(?,?,?,?)",
                (tid, feedback.content, revision, time.time()),
            )
            store.message(task["session_id"], "user", feedback.content)
            if state != "planned":
                store.transition(
                    tid, "planned", "用户反馈已加入计划，请审查后继续；不会执行旧计划的剩余动作"
                )
            store.event(
                tid,
                "steering",
                {
                    "content": feedback.content,
                    "revision": revision,
                    "plan_change": feedback.plan_change,
                },
            )
        elif action == "recover":
            decision = RecoveryDecision.model_validate(body)
            task = store.task(tid)
            if task["state"] not in ("paused", "planned", "failed", "waiting_for_user"):
                raise ValueError("请先暂停任务")
            call = store.one(
                "SELECT * FROM calls WHERE id=? AND task_id=?", (decision.call_id, tid)
            )
            if call["status"] != "interrupted":
                raise ValueError("此调用不需要恢复决定")
            store.run(
                "INSERT INTO recovery VALUES(?,?,?,?) ON CONFLICT(call_id) DO UPDATE SET decision=excluded.decision,note=excluded.note,created=excluded.created",
                (decision.call_id, decision.decision, decision.note, time.time()),
            )
            store.revise(tid)
            store.event(tid, "recovery_decision", decision.model_dump())
        else:
            raise HTTPException(404, "未知动作")
        return store.task(tid)

    @app.post("/api/approvals/{cid}")
    async def approve(cid: str, body: Approval):
        call = store.one("SELECT * FROM calls WHERE id=?", (cid,))
        if cid not in engine.pending:
            raise ValueError("授权请求已经失效")
        if body.allow:
            if body.scope == "once":
                engine.policy.grant(call["task_id"], call["tool"], cid)
            else:
                engine.policy.grant_rule(
                    store.task(call["task_id"]),
                    call["tool"],
                    json.loads(call["args"]),
                    body.scope,
                    body.hours,
                )
        store.event(call["task_id"], "approval_decision", {"call_id": cid, **body.model_dump()})
        engine.pending[cid].set()
        return {"ok": True}

    @app.get("/api/tasks/{tid}/events")
    async def events(tid: str, after: int = 0):
        return [
            {**x, "payload": json.loads(x["payload"])}
            for x in store.rows(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT 500", (tid, after)
            )
        ]

    @app.get("/api/tasks/{tid}/stream")
    async def stream(tid: str, request: Request, after: int = 0):
        store.task(tid)

        async def generate():
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
            while not await request.is_disconnected():
                rows = store.rows(
                    "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT 100",
                    (tid, cursor),
                )
                for row in rows:
                    cursor = row["id"]
                    row["payload"] = json.loads(row["payload"])
                    yield f"id: {cursor}\ndata: {dump(row)}\n\n"
                if not rows:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/api/tasks/{tid}/calls")
    async def calls(tid: str):
        return [
            {
                **x,
                "args": json.loads(x["args"]),
                "result": json.loads(x["result"]) if x["result"] else None,
            }
            for x in engine.history(tid, include_delegated=True)
        ]

    @app.get("/api/tasks/{tid}/browser")
    async def browser_state(tid: str):
        store.task(tid)
        session = engine.tools.browser.sessions.get(tid)
        return {"open": bool(session), "human": bool(session and session.get("human"))}

    @app.post("/api/tasks/{tid}/browser")
    async def browser_handoff(tid: str, body: dict):
        task = store.task(tid)
        if "browser.action" not in task["spec"]["tools"]:
            raise PermissionError("任务计划未启用浏览器")
        if type(body.get("human")) is not bool:
            raise ValueError("human 必须是布尔值")
        if task["state"] in (
            "running",
            "verifying",
            "awaiting_approval",
            "planned",
            "waiting_for_user",
        ):
            await engine.stop(tid, "paused")
        elif task["state"] != "paused":
            raise ValueError("请在尚未完成的任务中接管浏览器")
        result = await engine.tools.browser.handoff(task, body["human"])
        store.event(tid, "browser_handoff", result)
        return result

    @app.get("/api/tasks/{tid}/artifact")
    async def artifact(tid: str, path: str):
        try:
            resolved = artifact_path(store, tid, path)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return FileResponse(resolved, filename=resolved.name, media_type="application/octet-stream")

    @app.get("/api/tasks/{tid}/result")
    async def task_result(tid: str):
        return summary(store, tid)

    @app.get("/api/tasks/{tid}/preview")
    async def artifact_preview(tid: str, path: str):
        try:
            return preview(store, tid, path)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/attachments")
    async def attachment(file: UploadFile):
        folder = data / "attachments"
        folder.mkdir(exist_ok=True)
        ident = uid()
        path = folder / ident
        size = 0
        try:
            with path.open("wb") as out:
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > 20_000_000:
                        raise ValueError("附件最大 20 MB")
                    out.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        store.run(
            "INSERT INTO attachments VALUES(?,?,?,?,?)",
            (ident, file.filename or "unnamed", file.content_type, size, time.time()),
        )
        return {
            "id": ident,
            "name": file.filename,
            "size": size,
            "note": "将在下一条消息或新任务中作为附件数据发送；图片需要视觉能力。",
        }

    @app.post("/api/sessions/{sid}/plan")
    async def plan(sid: str, body: Message):
        provider = engine.provider(body.provider)
        if body.provider == "scripted":
            return {
                "questions": ["期望交付什么文件或功能？", "怎样验证结果达到要求？"],
                "detail": "确定性演示不会猜测任意需求。可手工填写计划，或使用真实模型完善。",
            }

        async def ignore(text):
            pass

        reply = await provider.reply(
            [
                {
                    "role": "system",
                    "content": "将用户需求整理为执行计划。最多问3个真正影响结果的问题；信息充分则questions为空。仅输出JSON，字段questions:list[str], goal:str, deliverables:list[str], acceptance:list[str], plan:list[str], tools:list[str]。工具可选："
                    + ",".join(SCHEMAS)
                    + "。不能请求密钥，不能声称已经执行。",
                },
                {"role": "user", "content": body.content},
            ],
            [],
            ignore,
        )
        usage = reply.usage or {
            "prompt_tokens": len(body.content) // 3,
            "completion_tokens": len(reply.text) // 3,
        }
        store.run(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)",
            (
                uid(),
                None,
                body.provider,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                int(reply.usage is None),
                None,
                time.time(),
            ),
        )
        result = json.loads(reply.text)
        expected = {"questions", "goal", "deliverables", "acceptance", "plan", "tools"}
        if set(result) != expected or not isinstance(result["goal"], str):
            raise ValueError("模型计划格式不符合 schema，请手动完善")
        for k in expected - {"goal"}:
            if not isinstance(result[k], list) or any(not isinstance(x, str) for x in result[k]):
                raise ValueError("计划字段必须是文本列表")
        if len(result["questions"]) > 3 or any(t not in SCHEMAS for t in result["tools"]):
            raise ValueError("计划超出允许范围")
        return result

    @app.put("/api/providers/{pid}")
    async def provider(pid: str, config: ProviderConfig):
        if pid != config.id or pid == "scripted":
            raise ValueError("provider ID 无效")
        config.model = config.model.strip()
        if not config.model:
            raise ValueError("模型 ID 不能为空；显示名称不能代替服务商的模型 ID")
        config.base_url = config.base_url.strip().rstrip("/")
        from urllib.parse import urlparse

        url = urlparse(config.base_url)
        if (
            url.scheme not in ("https", "http")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("API URL 无效，不得在 URL 中携带密钥或查询参数")
        if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("远程 API 必须使用 HTTPS")
        old = store.rows("SELECT config FROM providers WHERE id=?", (pid,))
        previous = json.loads(old[0]["config"]) if old else {}
        # Credential ownership is server-managed. A stale form must not erase or rebind it.
        config.credential_ref = previous.get("credential_ref")
        config.verified = {}
        store.run("INSERT OR REPLACE INTO providers VALUES(?,?)", (pid, dump(config.model_dump())))
        return {"ok": True}

    @app.get("/api/providers/{pid}/credential")
    async def credential_status(pid: str):
        config = json.loads(store.one("SELECT config FROM providers WHERE id=?", (pid,))["config"])
        ref = config.get("credential_ref")
        try:
            saved = bool(ref and keyring.get_password("LocalAgent", ref))
        except Exception:
            return {
                "saved": False,
                "detail": "凭据存储暂时无法读取，请重新保存或检查 Windows 凭据服务",
            }
        return {
            "saved": saved,
            "detail": (
                "密钥已保存，输入框留空表示保留；不会回显密钥。"
                if saved
                else "尚未保存可读取的密钥。"
            ),
        }

    @app.delete("/api/providers/{pid}")
    async def delete_provider(pid: str):
        if pid == "scripted":
            raise ValueError("内置演示模型不能删除")
        config = json.loads(store.one("SELECT config FROM providers WHERE id=?", (pid,))["config"])

        def uses(spec):
            return bool(spec) and (
                spec.get("provider") == pid or pid in spec.get("collaboration_mapping", {}).values()
            )

        if any(p == pid for s, p in inflight.values()) or any(
            uses(json.loads(t["spec"]))
            and (
                t["id"] in engine.enqueued
                or t["state"] in ("running", "verifying", "awaiting_approval")
            )
            for t in store.rows("SELECT * FROM tasks")
        ):
            raise ValueError("模型仍被活动请求或任务使用，请等待结束或暂停任务")
        if any(
            uses(json.loads(s["config"])["spec"])
            for s in store.rows("SELECT config FROM schedules WHERE enabled=1")
        ):
            raise ValueError("启用的定时任务仍使用此模型，请先暂停或修改定时任务")
        if config.get("credential_ref"):
            try:
                keyring.delete_password("LocalAgent", config["credential_ref"])
            except keyring.errors.PasswordDeleteError:
                pass
        store.run("DELETE FROM providers WHERE id=?", (pid,))
        return {"ok": True}

    @app.post("/api/providers/{pid}/credential")
    async def credential(pid: str, body: dict):
        config = json.loads(store.one("SELECT config FROM providers WHERE id=?", (pid,))["config"])
        secret = str(body.get("secret", ""))
        if not secret:
            raise ValueError("密钥不能为空")
        backend = keyring.get_keyring()
        if "Windows" not in type(backend).__module__:
            raise ValueError("未检测到 Windows 安全凭据后端，不回退到明文存储")
        ref = config.get("credential_ref") or uid()
        keyring.set_password("LocalAgent", ref, secret)
        config["credential_ref"] = ref
        store.run("UPDATE providers SET config=? WHERE id=?", (dump(config), pid))
        return {"ok": True}

    @app.post("/api/providers/{pid}/test")
    async def connection_test(pid: str, body: dict):
        ident = uid()
        inflight[ident] = (None, pid)
        try:
            return await test_impl(pid, body)
        finally:
            inflight.pop(ident, None)

    @app.get("/api/providers/{pid}/models")
    async def model_list(pid: str):
        if pid == "scripted":
            raise ValueError("内置演示模型没有远程模型列表")
        ident = uid()
        inflight[ident] = (None, pid)
        try:
            return {"models": await engine.provider(pid).list_models()}
        except Exception as exc:
            raise HTTPException(502, explain(exc))
        finally:
            inflight.pop(ident, None)

    async def test_impl(pid, body):
        async def ignore(text):
            pass

        kind = body.get("mode", "chat")
        if kind not in ("chat", "stream", "tools", "vision"):
            raise ValueError("未知能力测试")
        try:
            p = engine.provider(pid)
            if pid == "scripted":
                raise ValueError("Scripted 不能验证真实模型能力")
            p.config = p.config.model_copy(
                update={"streaming": kind == "stream", "tools": kind == "tools"}
            )
            messages = [{"role": "user", "content": "Reply with OK."}]
            tools = []
            if kind == "tools":
                messages = [
                    {
                        "role": "user",
                        "content": "Call echo exactly once with value equal to probe. Do not answer in text.",
                    }
                ]
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "parameters": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ]
            if kind == "vision":
                import base64
                import io

                from PIL import Image

                buffer = io.BytesIO()
                Image.new("RGB", (32, 32), "red").save(buffer, format="PNG")
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "What is the dominant color? Reply red, green, or blue.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,"
                                    + base64.b64encode(buffer.getvalue()).decode()
                                },
                            },
                        ],
                    }
                ]
            result = await p.reply(messages, tools, ignore)
            ok = bool(result.text)
            if kind == "tools":
                ok = (
                    len(result.calls) == 1
                    and result.calls[0]["name"] == "echo"
                    and result.calls[0]["arguments"] == {"value": "probe"}
                )
            if kind == "vision":
                ok = "red" in result.text.lower() or "红" in result.text
            original = json.loads(
                store.one("SELECT config FROM providers WHERE id=?", (pid,))["config"]
            )
            original.setdefault("verified", {})[kind] = (
                ("passed" if ok else "failed")
                + " · "
                + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                + " · samples=1"
            )
            store.run("UPDATE providers SET config=? WHERE id=?", (dump(original), pid))
            usage = result.usage or {
                "prompt_tokens": sum(len(dump(m)) for m in messages) // 3,
                "completion_tokens": len(result.text) // 3,
            }
            if not result.usage_id:
                store.run(
                    "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)",
                    (
                        uid(),
                        None,
                        pid,
                        int(usage.get("prompt_tokens", 0)),
                        int(usage.get("completion_tokens", 0)),
                        int(result.usage is None),
                        None,
                        time.time(),
                    ),
                )
            return {
                "ok": ok,
                "text": result.text,
                "tested": kind,
                "samples": 1,
                "detail": "仅验证本次协议/样本；不代表通用能力排名。工具 probe 没有执行系统动作。",
            }
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "detail": explain(exc)}

    @app.get("/api/grants")
    async def grants():
        return store.rows("SELECT * FROM grants ORDER BY expires DESC") + store.rows(
            "SELECT * FROM permission_rules ORDER BY expires DESC"
        )

    @app.delete("/api/grants/{gid}")
    async def revoke(gid: str):
        store.run("UPDATE grants SET revoked=1 WHERE id=?", (gid,))
        store.run("UPDATE permission_rules SET revoked=1 WHERE id=?", (gid,))
        return {"ok": True}

    @app.get("/api/skills")
    async def skills():
        folder = data / "skills"
        folder.mkdir(exist_ok=True)
        return catalog(ROOT, data)

    @app.get("/api/integrations/{kind}")
    async def integration(kind: str):
        if kind not in ("search", "email", "mcp"):
            raise ValueError("未知集成")
        rows = store.rows("SELECT value FROM settings WHERE key=?", (kind,))
        return json.loads(rows[0]["value"]) if rows else {"enabled": False}

    @app.get("/api/mcp/servers")
    async def mcp_servers():
        return [
            {
                **{k: v for k, v in json.loads(r["config"]).items() if k != "_revision"},
                "credential_saved": bool(r["credential_ref"]),
            }
            for r in store.rows("SELECT * FROM mcp_servers")
        ]

    @app.put("/api/mcp/servers/{ident}")
    async def mcp_server(ident: str, body: dict):
        secret = body.pop("secret", None)
        body.pop("credential_saved", None)
        config = MCPServer.model_validate(body)
        if config.id != ident:
            raise ValueError("MCP ID 不匹配")
        previous = store.rows("SELECT * FROM mcp_servers WHERE id=?", (ident,))
        ref = previous[0]["credential_ref"] if previous else None
        if secret:
            if config.transport != "http":
                raise ValueError("Bearer 密钥仅用于 HTTP MCP")
            if "Windows" not in type(keyring.get_keyring()).__module__:
                raise ValueError("需要 Windows 安全凭据存储")
            ref = ref or uid()
            keyring.set_password("LocalAgent", ref, str(secret))
        store.run(
            "INSERT OR REPLACE INTO mcp_servers VALUES(?,?,?)",
            (ident, dump({**config.model_dump(), "_revision": uid()}), ref),
        )
        return {"ok": True}

    @app.delete("/api/mcp/servers/{ident}")
    async def remove_mcp(ident: str):
        if engine.enqueued:
            raise ValueError("请先暂停或结束排队任务，再删除服务")
        row = store.one("SELECT * FROM mcp_servers WHERE id=?", (ident,))
        if row["credential_ref"]:
            try:
                keyring.delete_password("LocalAgent", row["credential_ref"])
            except keyring.errors.PasswordDeleteError:
                pass
        store.run("DELETE FROM mcp_servers WHERE id=?", (ident,))
        return {"ok": True}

    @app.get("/api/browser-settings")
    async def browser_settings():
        return {"channel": engine.tools.browser.channel or "chromium"}

    @app.put("/api/browser-settings")
    async def save_browser_settings(body: dict):
        channel = body.get("channel")
        if channel not in ("chromium", "msedge", "chrome"):
            raise ValueError("请选择 Chromium、Edge 或 Chrome")
        if engine.enqueued:
            raise ValueError("请先暂停任务再切换浏览器")
        await engine.tools.browser.close()
        engine.tools.browser.channel = None if channel == "chromium" else channel
        store.run("INSERT OR REPLACE INTO settings VALUES(?,?)", ("browser_channel", dump(channel)))
        return {"ok": True}

    @app.put("/api/integrations/{kind}")
    async def save_integration(kind: str, body: dict):
        if kind not in ("search", "email", "mcp"):
            raise ValueError("未知集成")
        secret = body.pop("secret", None)
        old = store.rows("SELECT value FROM settings WHERE key=?", (kind,))
        previous = json.loads(old[0]["value"]) if old else {}
        allowed = {
            "search": {
                "url",
                "results_path",
                "query_parameter",
                "url_field",
                "title_field",
                "snippet_field",
                "header",
                "prefix",
                "credential_ref",
                "enabled",
            },
            "email": {"enabled", "host", "port", "username", "sender", "credential_ref"},
            "mcp": {"enabled", "transport", "command", "args", "url", "tool", "arguments"},
        }
        if set(body) - allowed[kind]:
            raise ValueError("集成包含未知字段")
        if kind in ("email", "search"):
            body["credential_ref"] = previous.get("credential_ref")
        if kind == "search":
            from urllib.parse import urlparse

            url = urlparse(body.get("url", ""))
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
            ):
                raise ValueError("搜索 URL 必须为不含密钥/查询参数的 HTTPS 地址")
        if kind == "email" and body.get("enabled"):
            for k in ("host", "username", "sender"):
                if not body.get(k):
                    raise ValueError(f"邮箱配置缺少 {k}")
        if secret:
            backend = keyring.get_keyring()
            if "Windows" not in type(backend).__module__:
                raise ValueError("需要 Windows 安全凭据存储")
            ref = body.get("credential_ref") or uid()
            keyring.set_password("LocalAgent", ref, secret)
            body["credential_ref"] = ref
        store.run("INSERT OR REPLACE INTO settings VALUES(?,?)", (kind, dump(body)))
        return {"ok": True}

    @app.put("/api/skills/{name}")
    async def save_skill(name: str, body: dict):
        import re

        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
            raise ValueError("技能文件名无效")
        body = Skill.model_validate(body).model_dump()
        if any(t not in SCHEMAS or t == "checks.run" for t in body["tools"]):
            raise ValueError("技能依赖未知工具")
        folder = data / "skills"
        folder.mkdir(exist_ok=True)
        path = folder / (name + ".json")
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            body["version"] = max(body["version"], previous.get("version", 1) + 1)
            history = folder / "history"
            history.mkdir(exist_ok=True)
            (history / (name + "-" + uid() + ".json")).write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        path.write_text(dump(body), encoding="utf-8")
        return {"ok": True}

    @app.get("/api/schedules")
    async def schedules():
        return [
            {**x, "config": json.loads(x["config"])} for x in store.rows("SELECT * FROM schedules")
        ]

    @app.put("/api/schedules/{ident}")
    async def schedule(ident: str, config: Schedule):
        from zoneinfo import ZoneInfo

        ZoneInfo(config.timezone)
        if config.kind == "task":
            store.one("SELECT id FROM sessions WHERE id=?", (config.session_id,))
            Path(config.spec.workspace).resolve(strict=True)
        if config.authorized_until <= time.time():
            raise ValueError("调度授权已过期")
        store.run(
            "INSERT OR REPLACE INTO schedules VALUES(?,?,?,?)",
            (
                uid() if ident == "new" else ident,
                config.model_dump_json(),
                config.next_run,
                int(config.enabled),
            ),
        )
        return {"ok": True}

    @app.delete("/api/schedules/{ident}")
    async def delete_schedule(ident: str):
        store.run("DELETE FROM schedules WHERE id=?", (ident,))
        return {"ok": True}

    @app.post("/api/desktop/{action}")
    async def desktop_control(action: str):
        if action == "arm":
            engine.tools.desktop.arm()
        elif action == "stop":
            engine.tools.desktop.stop()
            if engine.active and not engine.active.done():
                tid = getattr(engine.active, "agent_task_id", None)
                if tid and store.task(tid)["state"] in (
                    "running",
                    "verifying",
                    "awaiting_approval",
                ):
                    await engine.stop(tid, "paused")
        else:
            raise ValueError("未知桌面动作")
        return {"stopped": engine.tools.desktop.stopped, "emergency": "Ctrl+Alt+F12"}

    @app.get("/api/memory-settings")
    async def memory_settings():
        rows = store.rows("SELECT value FROM settings WHERE key='auto_memory'")
        return {"auto_summary": bool(rows and json.loads(rows[0]["value"]))}

    @app.put("/api/memory-settings")
    async def save_memory_settings(body: dict):
        if type(body.get("auto_summary")) is not bool:
            raise ValueError("auto_summary 必须为布尔值")
        store.run(
            "INSERT OR REPLACE INTO settings VALUES(?,?)",
            ("auto_memory", dump(body["auto_summary"])),
        )
        return body

    @app.get("/api/memories/export")
    async def export_memories():
        return {
            "version": 1,
            "exported_at": time.time(),
            "memories": store.rows("SELECT * FROM memories ORDER BY updated DESC"),
            "history": store.rows("SELECT * FROM memory_history"),
        }

    @app.get("/api/memories/{mid}/history")
    async def memory_history(mid: str):
        return [
            {**r, "snapshot": json.loads(r["snapshot"])}
            for r in store.rows(
                "SELECT * FROM memory_history WHERE memory_id=? ORDER BY id DESC", (mid,)
            )
        ]

    @app.get("/api/memories")
    async def memories(q: str = ""):
        return store.search_memories(q, limit=1000 if not q else 50)

    @app.put("/api/memories/{mid}")
    async def memory(mid: str, body: dict):
        if (
            not isinstance(body.get("content"), str)
            or not body["content"].strip()
            or len(body["content"]) > 20000
        ):
            raise ValueError("记忆内容需为 1 至 20000 字符")
        if body.get("kind", "explicit") not in ("explicit", "inferred", "unconfirmed"):
            raise ValueError("记忆类型无效")
        return {
            "id": store.memory(
                str(body.get("scope", "personal")),
                str(body["content"]),
                body.get("kind", "explicit"),
                "user",
                None if mid == "new" else mid,
            )
        }

    @app.delete("/api/memories/{mid}")
    async def delete_memory(mid: str):
        with store.transaction() as db:
            db.execute("DELETE FROM memory_history WHERE memory_id=?", (mid,))
            db.execute("DELETE FROM memories WHERE id=?", (mid,))
            db.execute("DELETE FROM memory_fts WHERE id=?", (mid,))
        return {"ok": True}

    if (ROOT / "dist/web").exists():
        app.mount("/", StaticFiles(directory=ROOT / "dist/web", html=True), name="web")
    return app
