#!/bin/bash
set -e

echo "========================================================"
echo "  TinyOlly - Install MkDocs"
echo "========================================================"
echo ""

# Use $PYTHON if set, otherwise the first python3 (or python) on PATH
PYTHON="${PYTHON:-$(command -v python3 || command -v python || true)}"
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 8))' &> /dev/null; then
    echo "✗ Python 3.8+ not found (set PYTHON=/path/to/python3 to choose one)"
    exit 1
fi
PY_VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "Using $PYTHON (Python $PY_VERSION)"

echo "Installing MkDocs and required plugins into a virtual environment..."
echo ""

VENV_DIR="$HOME/.venv/mkdocs"

# Recreate venv if its interpreter is gone or is a different Python version
if [ -d "$VENV_DIR" ]; then
    VENV_VERSION="$("$VENV_DIR/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2> /dev/null || true)"
    if [ "$VENV_VERSION" != "$PY_VERSION" ]; then
        echo "Existing venv uses Python ${VENV_VERSION:-<missing>}; recreating with $PY_VERSION..."
        rm -rf "$VENV_DIR"
    fi
fi

# Create venv if it doesn't exist (venv bundles pip, so no system pip needed)
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Install packages into the venv
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install mkdocs mkdocs-material pymdown-extensions

echo ""
echo "========================================================"
echo "  MkDocs Installation Complete!"
echo "========================================================"
echo ""
echo "Installed packages:"
echo "  - mkdocs: Static site generator"
echo "  - mkdocs-material: Material theme for MkDocs"
echo "  - pymdown-extensions: Markdown extensions"
echo ""
echo "Virtual environment: $HOME/.venv/mkdocs"
echo ""
echo "To activate the venv:"
echo "  source ~/.venv/mkdocs/bin/activate"
echo ""
echo "To serve documentation locally:"
echo "  mkdocs serve"
echo ""
echo "To build documentation:"
echo "  mkdocs build"
echo ""
echo "To deploy to GitHub Pages:"
echo "  ./mkdocs-deploy.sh   (from the repo root)"
echo ""
