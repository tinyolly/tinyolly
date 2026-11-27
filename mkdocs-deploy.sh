#!/bin/bash
set -e

# Activate virtual environment if it exists, then run zensical
VENV_DIR="$HOME/.venv/mkdocs"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
elif [ -d "$(dirname "${BASH_SOURCE[0]}")/.venv" ]; then
    source "$(dirname "${BASH_SOURCE[0]}")/.venv/bin/activate"
fi

# Build documentation using Zensical
python3 -m zensical build --clean

# Publishes the site to the gh-pages branch of the remote (default: origin; override with REMOTE=...)
python3 -m ghp_import -p -r "${REMOTE:-origin}" site
