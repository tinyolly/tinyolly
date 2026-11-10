import asyncio
import os
import tempfile

import pytest_asyncio

from tinyolly_common.storage_sqlite import StorageSQLite


@pytest_asyncio.fixture
async def storage():
    with tempfile.TemporaryDirectory() as d:
        s = StorageSQLite(db_path=os.path.join(d, "t.db"), ttl=60)
        try:
            yield s
        finally:
            task = getattr(s, "_cleanup_task", None)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
