#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[ -x .venv/bin/python ] || ./install.sh >/dev/null
.venv/bin/pip install -q -r requirements-test.txt
.venv/bin/python -m pytest tests -q "$@"
