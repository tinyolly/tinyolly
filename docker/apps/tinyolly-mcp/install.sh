#!/usr/bin/env bash
# Set up the TinyOlly MCP server in a local venv and print how to register it with your agent.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -x "$DIR/.venv/bin/python" ] || python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
cat <<EOF
TinyOlly MCP server ready.

Claude Code:
  claude mcp add tinyolly -- $DIR/.venv/bin/python $DIR/server.py

Claude Desktop: edit ~/Library/Application Support/Claude/claude_desktop_config.json, add under "mcpServers", then quit and reopen Claude:
  "tinyolly": { "command": "$DIR/.venv/bin/python", "args": ["$DIR/server.py"] }

Zed (~/.config/zed/settings.json):
  "context_servers": { "tinyolly": { "command": "$DIR/.venv/bin/python", "args": ["$DIR/server.py"] } }

Point it at a different TinyOlly with TINYOLLY_URL (default http://localhost:5005).
EOF
