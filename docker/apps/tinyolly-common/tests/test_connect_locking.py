"""Opening a connection must not need the write lock: under heavy ingest /health returned 503 ("database is locked")."""
import asyncio
import sqlite3
import time

from tinyolly_common.storage_sqlite import StorageSQLite


def test_health_check_answers_while_another_process_is_writing(tmp_path):
    path = str(tmp_path / "t.db")

    async def run():
        storage = StorageSQLite(db_path=path)
        assert await storage.is_connected()
        writer = sqlite3.connect(path, isolation_level=None)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO kv (key, value, expires_at) VALUES ('k', 'v', 0)")
        try:
            started = time.monotonic()
            assert await storage.is_connected()
            assert time.monotonic() - started < 1
        finally:
            writer.execute("ROLLBACK")
            writer.close()

    asyncio.run(run())
