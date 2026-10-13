import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

from .models import STATES


def uid():
    return uuid.uuid4().hex


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def atomic(method):
    """A synchronous unit of work: never await while holding a transaction."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.transaction():
            return method(self, *args, **kwargs)

    return wrapped


@dataclass(frozen=True)
class WriteResult:
    lastrowid: int | None
    rowcount: int


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connection() as db:
            db.executescript(Path(__file__).with_name("migration.sql").read_text())

    @contextmanager
    def connection(self):
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            yield existing
            return
        # No shared sqlite Connection crosses thread boundaries. WAL permits readers
        # alongside writers; busy_timeout lets separate writer units queue safely.
        db = sqlite3.connect(self.root / "agent.db", timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        """Atomic synchronous work, using savepoints for nested operations.

        Every outer transaction owns a connection on the calling thread. An inner
        run() must never commit another operation's unfinished transaction.
        """
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            savepoint = "sp_" + uid()
            existing.execute("SAVEPOINT " + savepoint)
            try:
                yield existing
            except BaseException:
                existing.execute("ROLLBACK TO " + savepoint)
                raise
            finally:
                existing.execute("RELEASE " + savepoint)
            return
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._local.connection = db
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                del self._local.connection

    def run(self, sql, args=()):
        with self.connection() as db:
            cur = db.execute(sql, args)
            return WriteResult(cur.lastrowid, cur.rowcount)

    def many(self, sql, args):
        with self.transaction() as db:
            db.executemany(sql, args)

    def rows(self, sql, args=()):
        with self.connection() as db:
            return [dict(x) for x in db.execute(sql, args)]

    def one(self, sql, args=()):
        with self.connection() as db:
            row = db.execute(sql, args).fetchone()
            if row is None:
                raise KeyError("记录不存在")
            return dict(row)

    def event(self, task, kind, payload):
        return self.run(
            "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
            (task, kind, dump(payload), time.time()),
        ).lastrowid

    @atomic
    def task(self, task_id):
        row = self.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        row["spec"] = json.loads(row["spec"])
        first = self.one(
            "SELECT MIN(created) started FROM events WHERE task_id=? AND type='state' AND json_extract(payload,'$.state')='running'",
            (task_id,),
        )["started"]
        latest = self.rows(
            "SELECT created,payload FROM events WHERE task_id=? AND type='state' ORDER BY id DESC LIMIT 1",
            (task_id,),
        )
        row["state_detail"] = json.loads(latest[0]["payload"]).get("detail", "") if latest else ""
        row["stop_reason"] = json.loads(latest[0]["payload"]).get("reason") if latest else None
        row["timing"] = {
            "started": first,
            "ended": (
                None
                if row["state"] in ("running", "verifying")
                else (latest[0]["created"] if latest else row["updated"])
            ),
        }

        runtime = self.runtime(task_id)
        row["revision"] = runtime["revision"]
        row["verification"] = (
            json.loads(runtime["verification"]) if runtime["verification"] else None
        )
        row["needs_recovery"] = bool(
            self.rows(
                "SELECT c.id FROM calls c LEFT JOIN recovery r ON r.call_id=c.id WHERE c.task_id=? AND c.status='interrupted' AND r.call_id IS NULL",
                (task_id,),
            )
        )
        return row

    @atomic
    def runtime(self, task_id):
        self.run("INSERT OR IGNORE INTO task_runtime(task_id) VALUES(?)", (task_id,))
        return self.one("SELECT * FROM task_runtime WHERE task_id=?", (task_id,))

    @atomic
    def revise(self, task_id):
        self.runtime(task_id)
        self.run(
            "UPDATE task_runtime SET revision=revision+1,verified_revision=NULL,verification=NULL WHERE task_id=?",
            (task_id,),
        )
        return self.runtime(task_id)["revision"]

    @atomic
    def transition(self, task_id, state, detail="", reason=None):
        current = self.task(task_id)["state"]
        if state not in STATES[current]:
            raise ValueError(f"非法状态转换 {current} → {state}")
        self.run("UPDATE tasks SET state=?,updated=? WHERE id=?", (state, time.time(), task_id))
        self.event(task_id, "state", {"state": state, "detail": detail, "reason": reason})

    @atomic
    def recover(self):
        for t in self.rows(
            "SELECT id FROM tasks WHERE state IN ('running','verifying','awaiting_approval')"
        ):
            self.run("UPDATE tasks SET state='paused' WHERE id=?", (t["id"],))
            self.event(
                t["id"],
                "interrupted",
                {"detail": "服务中断。请审查调用日志后继续；未完成动作不会自动重放。"},
            )
        self.run(
            "UPDATE calls SET status='not_executed',result=? WHERE status='pending'",
            (dump({"status": "not_executed", "error": "服务中断前尚未派发，可以重新请求授权"}),),
        )
        self.run(
            "UPDATE calls SET status='interrupted',result=? WHERE status='running'",
            (
                dump(
                    {
                        "status": "interrupted",
                        "error": "副作用结果不确定，必须审查后选择跳过或明确重试",
                    }
                ),
            ),
        )
        self.run("UPDATE grants SET revoked=1 WHERE scope=?", ("once",))
        self.run("UPDATE model_requests SET status='interrupted' WHERE status='running'")

    def message(self, session, role, content):
        self.run(
            "INSERT INTO messages VALUES(?,?,?,?,?)", (uid(), session, role, content, time.time())
        )

    @atomic
    def memory(self, scope, content, kind="explicit", source="user", memory_id=None):
        memory_id = memory_id or uid()
        now = time.time()
        old = self.rows("SELECT * FROM memories WHERE id=?", (memory_id,))
        with self.transaction() as db:
            if old:
                db.execute(
                    "INSERT INTO memory_history(memory_id,snapshot,created) VALUES(?,?,?)",
                    (memory_id, dump(old[0]), now),
                )
            db.execute(
                "INSERT INTO memories VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content,scope=excluded.scope,kind=excluded.kind,source=excluded.source,updated=excluded.updated",
                (memory_id, scope, content, kind, source, now, now),
            )
            db.execute("DELETE FROM memory_fts WHERE id=?", (memory_id,))
            db.execute("INSERT INTO memory_fts VALUES(?,?)", (memory_id, content))
        return memory_id

    def search_memories(self, q="", scopes=None, limit=50):
        filters = []
        args = []
        if scopes:
            filters.append("scope IN (" + ",".join("?" for _ in scopes) + ")")
            args.extend(scopes)
        if q.strip():
            # Quoted literal FTS query, with substring fallback for Chinese token boundaries.
            query = '"' + q.strip().replace('"', '""') + '"'
            filters.append(
                "(id IN (SELECT id FROM memory_fts WHERE memory_fts MATCH ?) OR instr(lower(content),lower(?))>0)"
            )
            args.extend([query, q.strip()])
        return self.rows(
            "SELECT * FROM memories"
            + (" WHERE " + " AND ".join(filters) if filters else "")
            + " ORDER BY updated DESC LIMIT ?",
            [*args, limit],
        )
