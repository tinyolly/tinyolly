"""Change markers ("events"): things that happened to the system (a scenario applied, a deploy) stored next to telemetry."""


import json
import time
import uuid
from typing import Any, Dict, List, Optional

from .storage_common import logger


class EventsMixin:
    """Change markers ("events"): things that happened to the system (a scenario applied, a deploy) stored next to telemetry."""

    async def add_event(
        self,
        title: str,
        source: str = "api",
        kind: str = "change",
        attributes: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        await self._ensure_initialized()
        if ts is None:
            ts = time.time()
        ts = float(ts)
        if attributes is None:
            attributes = {}

        event_id = uuid.uuid4().hex
        now = time.time()
        expires_at = now + self.ttl
        data = json.dumps({"title": title, "source": source, "kind": kind, "attributes": attributes})

        await self._retry_locked(lambda: self._add_event_once(event_id, ts, expires_at, data))

        return {
            "id": event_id,
            "timestamp": ts,
            "title": title,
            "source": source,
            "kind": kind,
            "attributes": attributes,
        }

    async def _add_event_once(self, event_id: str, ts: float, expires_at: float, data: str) -> None:
        async with self._write_lock:
            conn = await self._connect()
            try:
                await conn.execute("BEGIN IMMEDIATE")
                await conn.execute(
                    "INSERT OR REPLACE INTO events(event_id, ts, expires_at, data) VALUES (?, ?, ?, ?)",
                    (event_id, ts, expires_at, data),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()

    async def get_events(self, since_ts: Optional[float] = None, limit: int = 100) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        now = time.time()
        conn = await self._connect()
        try:
            if since_ts is not None:
                sql = "SELECT event_id, ts, data FROM events WHERE expires_at > ? AND ts >= ? ORDER BY ts DESC LIMIT ?"
                params = (now, float(since_ts), limit)
            else:
                sql = "SELECT event_id, ts, data FROM events WHERE expires_at > ? ORDER BY ts DESC LIMIT ?"
                params = (now, limit)

            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()

            events: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    payload = json.loads(row[2])
                except Exception as e:
                    logger.error(f"Error parsing event: {e}", exc_info=True)
                    continue
                events.append(
                    {
                        "id": row[0],
                        "timestamp": row[1],
                        "title": payload.get("title"),
                        "source": payload.get("source"),
                        "kind": payload.get("kind"),
                        "attributes": payload.get("attributes", {}),
                    }
                )
            return events
        except Exception as e:
            logger.error(f"Error getting events: {e}", exc_info=True)
            return []
        finally:
            await conn.close()
