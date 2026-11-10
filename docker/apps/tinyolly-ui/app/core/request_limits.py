"""Request body helpers that enforce size limits while streaming."""

import json
import os
from typing import Any

from fastapi import HTTPException, Request

MAX_INGEST_BODY_BYTES = int(os.getenv("MAX_INGEST_BODY_BYTES", str(5 * 1024 * 1024)))


async def read_json_body(request: Request, max_bytes: int = MAX_INGEST_BODY_BYTES) -> Any:
    """Read and parse a JSON request body, never buffering more than max_bytes.

    The Content-Length header is only a hint (chunked requests have none, and clients can lie), so the
    limit is enforced on the bytes actually received. Raises HTTPException 400 for a bad Content-Length
    and 413 when the body is too large; json.JSONDecodeError / ValueError propagate for bad JSON.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from None
        if declared_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="Payload too large")

    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            raise HTTPException(status_code=413, detail="Payload too large")
        chunks.append(chunk)
    return json.loads(b"".join(chunks))
