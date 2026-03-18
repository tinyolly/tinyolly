#!/bin/bash
set -e

echo "========================================================"
echo "  TinyOlly - Install MkDocs"
echo "========================================================"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 is not installed or not in PATH"
    echo "Please install Python 3 first"
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "✗ pip3 is not installed or not in PATH"
    echo "Please install pip3 first"
    exit 1
fi

echo "Installing MkDocs and required plugins into a virtual environment..."
echo ""

VENV_DIR="$HOME/.venv/mkdocs"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Install packages into the venv
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install mkdocs mkdocs-material pymdown-extensions

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
echo "  ./mkdocs-deploy.sh"
echo ""
