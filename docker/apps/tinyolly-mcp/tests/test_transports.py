"""Real transports: the server started as a subprocess over stdio and over streamable HTTP (no TinyOlly needed)."""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
SERVER = str(ROOT / "server.py")


async def _exercise(session):
    await session.initialize()
    tools = {t.name for t in (await session.list_tools()).tools}
    assert {"list_services", "chart_metric", "chart_service_map", "list_skills", "read_doc", "get_trace"} <= tools
    skills = json.loads((await session.call_tool("list_skills", {})).content[0].text)
    assert len(skills) >= 6
    assert {p.name for p in (await session.list_prompts()).prompts} >= {"tinyolly-triage"}
    doc = json.loads((await session.call_tool("read_doc", {"name": "mcp"})).content[0].text)
    assert doc["title"] == "MCP server"
    err = await session.call_tool("list_services", {})          # TinyOlly unreachable -> a clear error, not a hang
    assert err.is_error or "Cannot reach" in err.content[0].text or "[" in err.content[0].text


def test_stdio_transport():
    async def main():
        params = StdioServerParameters(command=sys.executable, args=[SERVER], env={"TINYOLLY_URL": "http://127.0.0.1:9"})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await _exercise(s)
    asyncio.run(main())


def test_streamable_http_transport():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([sys.executable, SERVER, "--http", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={"TINYOLLY_URL": "http://127.0.0.1:9", "PATH": "/usr/bin:/bin"})
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("HTTP server did not start")

        async def main():
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as streams:
                async with ClientSession(streams[0], streams[1]) as s:
                    await _exercise(s)
        asyncio.run(main())
    finally:
        proc.terminate()
        proc.wait(timeout=10)
