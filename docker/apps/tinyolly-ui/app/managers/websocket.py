"""WebSocket connection manager"""

import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates.

    Handles multiple concurrent WebSocket connections and broadcasts
    updates to all connected clients.
    """

    def __init__(self):
        """Initialize connection manager with empty connections set."""
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection.

        Args:
            websocket (WebSocket): WebSocket connection to register
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from active connections.

        Args:
            websocket (WebSocket): WebSocket connection to remove
        """
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSocket clients.

        Args:
            message (dict): Message to broadcast (will be JSON-serialized)
        """
        if not self.active_connections:
            return

        disconnected = set()
        # Iterate a snapshot: connect()/disconnect() run in other tasks while we await each send.
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)
