from concurrent.futures import ThreadPoolExecutor

import pytest

from services.agent.store import Store


def test_concurrent_units_do_not_lose_updates(tmp_path):
    store = Store(tmp_path)
    store.run("CREATE TABLE counter(n INTEGER)")
    store.run("INSERT INTO counter VALUES(0)")

    def increment(_):
        with store.transaction():
            n = store.one("SELECT n FROM counter")["n"]
            store.run("UPDATE counter SET n=?", (n + 1,))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(80)))
    assert store.one("SELECT n FROM counter")["n"] == 80


def test_nested_writes_do_not_commit_outer_unit(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.run("INSERT INTO settings VALUES('outer','1')")
            with store.transaction():
                store.run("INSERT INTO settings VALUES('inner','1')")
            raise RuntimeError("fault after nested writes")
    assert store.rows("SELECT * FROM settings") == []
    with store.transaction():
        store.run("INSERT INTO settings VALUES('kept','1')")
        with pytest.raises(ValueError):
            with store.transaction():
                store.run("INSERT INTO settings VALUES('discarded','1')")
                raise ValueError("savepoint rollback")
    assert [r["key"] for r in store.rows("SELECT * FROM settings")] == ["kept"]


def test_reader_cannot_see_another_threads_uncommitted_write(tmp_path):
    store = Store(tmp_path)
    with store.transaction():
        store.run("INSERT INTO settings VALUES('pending','1')")
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(store.rows, "SELECT * FROM settings").result(timeout=3) == []
    assert len(store.rows("SELECT * FROM settings")) == 1


def test_memory_and_search_index_rollback_together(tmp_path, monkeypatch):
    store = Store(tmp_path)
    mid = store.memory("scope", "old content")
    store.run(
        "CREATE TRIGGER reject_memory BEFORE INSERT ON memory_history BEGIN SELECT RAISE(ABORT, 'fault'); END"
    )
    with pytest.raises(Exception, match="fault"):
        store.memory("scope", "new content", memory_id=mid)
    assert store.search_memories("old content")[0]["id"] == mid
    assert not store.search_memories("new content")
