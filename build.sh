#!/usr/bin/env bash
set -e

source .venv/bin/activate

# 1. Build frontend
echo "→ Building frontend..."
cd frontend && npm run build && cd ..

# 2. Build macOS .app bundle via spec file
echo "→ Building EyeDoc.app with PyInstaller..."
pyinstaller --noconfirm app.spec

echo "✓ Build complete. Output: dist/EyeDoc.app"
echo "  Run with:  open dist/EyeDoc.app"