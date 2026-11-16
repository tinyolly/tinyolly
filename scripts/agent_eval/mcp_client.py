"""Minimal MCP (streamable HTTP) client: list tools and call them. Standard library only."""
import json
import urllib.request

_HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


class MCPClient:
    def __init__(self, url):
        self.url, self.sid = url, None
        self.sid, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "agent-eval", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, body):
        headers = dict(_HEADERS)
        if self.sid:
            headers["mcp-session-id"] = self.sid
        req = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = [ln[5:].strip() for ln in resp.read().decode().splitlines() if ln.startswith("data:")]
            return resp.headers.get("mcp-session-id"), (json.loads(data[0]) if data else None)

    def list_tools(self):
        return self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[1]["result"]["tools"]

    def call_tool(self, name, args):
        _, reply = self._post({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
        if reply.get("error"):
            return f"error: {reply['error']}"
        return "\n".join(c["text"] for c in reply["result"].get("content", []) if c["type"] == "text") or "(no text result)"

    def call_content(self, name, args):
        """Return the raw content list (text and image items) of a tool result."""
        _, reply = self._post({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
        if reply.get("error"):
            raise RuntimeError(str(reply["error"]))
        return reply["result"].get("content", [])
