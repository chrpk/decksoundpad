#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLUGIN_NAME="DeckSoundpad"
VERSION="$(node -p "JSON.parse(require('fs').readFileSync('package.json', 'utf8')).version")"
BUILD_ID="$(date -u +%Y%m%d%H%M%S)"
OUT_DIR="$ROOT_DIR/out"
STAGE_DIR="$OUT_DIR/package-stage-$BUILD_ID"
PLUGIN_DIR="$STAGE_DIR/$PLUGIN_NAME"
ZIP_TMP="$OUT_DIR/$PLUGIN_NAME-v$VERSION-full.$BUILD_ID.zip"
ZIP_PATH="$OUT_DIR/$PLUGIN_NAME-v$VERSION-full.zip"

corepack pnpm build

mkdir -p "$PLUGIN_DIR"

cp LICENSE README.md plugin.json package.json main.py "$PLUGIN_DIR/"
cp -R dist "$PLUGIN_DIR/dist"
cp -R defaults "$PLUGIN_DIR/defaults"
cp -R docs "$PLUGIN_DIR/docs"

mkdir -p "$PLUGIN_DIR/backend"
cp backend/__init__.py "$PLUGIN_DIR/backend/__init__.py"
rsync -a --exclude __pycache__ --exclude '*.pyc' backend/decksoundpad "$PLUGIN_DIR/backend/"

(
  cd "$STAGE_DIR"
  zip -qr "$ZIP_TMP" "$PLUGIN_NAME" \
    -x '*.DS_Store' \
    -x '*.pyc' \
    -x '*__pycache__*' \
    -x '*.map'
)

mv "$ZIP_TMP" "$ZIP_PATH"

echo "Packaged $ZIP_PATH"
