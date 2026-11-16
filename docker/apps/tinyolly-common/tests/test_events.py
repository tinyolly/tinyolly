"""Change markers ("events"): things that happened to the system (a scenario applied, a deploy) stored next to telemetry."""
import time

import pytest


@pytest.mark.asyncio
async def test_add_and_get_events_newest_first(storage):
    now = time.time()
    e1 = await storage.add_event("applied canary", source="demo", kind="scenario", attributes={"scenario": "canary"}, ts=now - 30)
    e2 = await storage.add_event("applied fault", ts=now - 10)
    assert e1["id"] and e2["id"] and e1["id"] != e2["id"]
    assert e2["title"] == "applied fault" and e2["kind"] == "change" and e2["source"] == "api"
    assert e2["timestamp"] == pytest.approx(now - 10)
    got = await storage.get_events()
    assert [e["title"] for e in got] == ["applied fault", "applied canary"]
    assert got[1]["attributes"] == {"scenario": "canary"} and got[1]["source"] == "demo" and got[1]["kind"] == "scenario"


@pytest.mark.asyncio
async def test_timestamp_defaults_to_now(storage):
    e = await storage.add_event("x")
    assert abs(e["timestamp"] - time.time()) < 5


@pytest.mark.asyncio
async def test_since_and_limit(storage):
    now = time.time()
    for i in range(5):
        await storage.add_event(f"e{i}", ts=now - 100 + i * 10)
    assert [e["title"] for e in await storage.get_events(since_ts=now - 85)] == ["e4", "e3", "e2"]
    assert [e["title"] for e in await storage.get_events(limit=2)] == ["e4", "e3"]


@pytest.mark.asyncio
async def test_clear_all_removes_events(storage):
    await storage.add_event("x")
    await storage.clear_all()
    assert await storage.get_events() == []


@pytest.mark.asyncio
async def test_expired_events_are_cleaned_up(storage):
    await storage.add_event("old")
    conn = await storage._connect()
    try:
        await conn.execute("UPDATE events SET expires_at = 0")
        await conn.commit()
    finally:
        await conn.close()
    await storage._cleanup_expired_and_trim()
    assert await storage.get_events() == []
