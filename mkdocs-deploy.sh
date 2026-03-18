#!/bin/bash
# Activate virtual environment if it exists, then run mkdocs
VENV_DIR="$HOME/.venv/mkdocs"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
elif [ -d "$(dirname "${BASH_SOURCE[0]}")/.venv" ]; then
    source "$(dirname "${BASH_SOURCE[0]}")/.venv/bin/activate"
fi
python3 -m mkdocs gh-deploy --remote-name upstream