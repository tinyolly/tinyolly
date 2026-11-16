"""POST/GET /api/events: change markers."""
import pytest

from tinyolly_common.storage_sqlite import StorageSQLite


@pytest.mark.asyncio
async def test_create_and_list_events(tmp_path):
    from app.routers import query
    st = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=60)
    try:
        created = await query.create_event(query.EventIn(title="applied fault", source="demo", kind="scenario",
                                                         attributes={"scenario": "fault"}), storage=st)
        assert created["title"] == "applied fault" and created["id"]
        listed = await query.list_events(minutes=10, limit=50, storage=st)
        assert [e["title"] for e in listed] == ["applied fault"] and listed[0]["attributes"] == {"scenario": "fault"}
    finally:
        if st._cleanup_task:
            st._cleanup_task.cancel()


@pytest.mark.asyncio
async def test_list_respects_window_and_limit(tmp_path):
    import time

    from app.routers import query
    st = StorageSQLite(db_path=str(tmp_path / "t.db"), ttl=3600)
    try:
        now = time.time()
        await st.add_event("old", ts=now - 3000)
        for i in range(3):
            await st.add_event(f"new{i}", ts=now - 10 * (3 - i))
        assert [e["title"] for e in await query.list_events(minutes=5, limit=50, storage=st)] == ["new2", "new1", "new0"]
        assert len(await query.list_events(minutes=100, limit=2, storage=st)) == 2
    finally:
        if st._cleanup_task:
            st._cleanup_task.cancel()


def test_event_model_requires_title():
    from pydantic import ValidationError

    from app.routers import query
    with pytest.raises(ValidationError):
        query.EventIn(title="")
