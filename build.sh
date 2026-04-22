#!/usr/bin/env bash
# Build script for Zepp PC Manager on Linux
# Requires: Python 3.10+, uv, and system Qt dependencies

set -euo pipefail

echo "========================================"
echo " Zepp PC Manager - Linux Build"
echo "========================================"

# Create venv if needed
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    uv venv .venv
fi
source .venv/bin/activate
uv pip install -e ".[dev,gui]"

echo ""
echo "Installing build dependencies..."
uv pip install pyinstaller

echo ""
echo "Running tests..."
pytest tests/ -v

echo ""
echo "Building executable..."
pyinstaller build.spec --clean

echo ""
echo "========================================"
echo " Build complete!"
echo " Output: dist/zepp-pc"
echo "========================================"
