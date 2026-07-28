#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLUGIN_NAME="DeckSoundpad"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required packaging command not found: $1" >&2
    exit 1
  fi
}

for command_name in bash node corepack git zip find cp rm mkdir mv basename mktemp; do
  require_command "$command_name"
done

if command -v shasum >/dev/null 2>&1; then
  CHECKSUM_TOOL="shasum"
elif command -v sha256sum >/dev/null 2>&1; then
  CHECKSUM_TOOL="sha256sum"
else
  echo "Required checksum command not found: install shasum or sha256sum" >&2
  exit 1
fi

bash scripts/validate_license_notices.sh

VERSION="$(node -p "JSON.parse(require('fs').readFileSync('package.json', 'utf8')).version")"
OUT_DIR="$ROOT_DIR/out"
mkdir -p "$OUT_DIR"

STAGE_DIR="$(mktemp -d "$OUT_DIR/package-stage.XXXXXX")"
PLUGIN_DIR="$STAGE_DIR/$PLUGIN_NAME"
ZIP_TMP="$OUT_DIR/$PLUGIN_NAME-v$VERSION-full.$(basename "$STAGE_DIR").zip"
ZIP_PATH="$OUT_DIR/$PLUGIN_NAME-v$VERSION-full.zip"
ZIP_NAME="$(basename "$ZIP_PATH")"

cleanup() {
  rm -rf "$STAGE_DIR" "$ZIP_TMP"
}
trap cleanup EXIT

corepack pnpm build

mkdir -p "$PLUGIN_DIR"
cp LICENSE README.md SECURITY.md SUPPORT.md CHANGELOG.md plugin.json package.json main.py "$PLUGIN_DIR/"
cp -R dist "$PLUGIN_DIR/dist"
cp -R defaults "$PLUGIN_DIR/defaults"
mkdir -p "$PLUGIN_DIR/docs"
runtime_docs=(
  "COMPATIBILITY.md"
  "DIAGNOSTICS.md"
  "INSTALLATION.md"
  "PRIVACY.md"
  "THIRD_PARTY_LICENSES.md"
  "THIRD_PARTY_NOTICES.md"
  "TROUBLESHOOTING.md"
)
for doc in "${runtime_docs[@]}"; do
  cp "docs/$doc" "$PLUGIN_DIR/docs/"
done

mkdir -p "$PLUGIN_DIR/backend"
cp backend/__init__.py "$PLUGIN_DIR/backend/__init__.py"
cp -R backend/decksoundpad "$PLUGIN_DIR/backend/"
find "$PLUGIN_DIR/backend/decksoundpad" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PLUGIN_DIR/backend/decksoundpad" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.pyd' \) -exec rm -f {} +

node - "$PLUGIN_DIR" "$ZIP_NAME" <<'NODE'
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const pluginDir = process.argv[2];
const artifactName = process.argv[3];
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
const plugin = JSON.parse(fs.readFileSync("plugin.json", "utf8"));
const backendText = fs.readFileSync("backend/decksoundpad/__init__.py", "utf8");
const backendMatch = backendText.match(/__version__\s*=\s*['"]([^'"]+)['"]/);

function gitValue(args, fallback) {
  try {
    return execFileSync("git", args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return fallback;
  }
}

const status = gitValue(["status", "--porcelain=v1", "--untracked-files=all"], "");
const manifest = {
  name: plugin.name,
  packageName: pkg.name,
  version: pkg.version,
  backendVersion: backendMatch ? backendMatch[1] : null,
  apiVersion: plugin.api_version,
  flags: plugin.flags || [],
  artifact: artifactName,
  sourceCommit: gitValue(["rev-parse", "HEAD"], null),
  sourceDirty: status.length > 0,
  generatedAt: new Date().toISOString(),
};

fs.writeFileSync(
  path.join(pluginDir, "RELEASE_MANIFEST.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
NODE

(
  cd "$STAGE_DIR"
  zip -qr "$ZIP_TMP" "$PLUGIN_NAME" \
    -x '*.DS_Store' \
    -x '*.pyc' \
    -x '*.pyo' \
    -x '*.pyd' \
    -x '*__pycache__*' \
    -x '*.map'
)

mv "$ZIP_TMP" "$ZIP_PATH"

echo "Packaged $ZIP_PATH"

if [[ "$CHECKSUM_TOOL" == "shasum" ]]; then
  (cd "$OUT_DIR" && shasum -a 256 "$ZIP_NAME" > "$ZIP_NAME.sha256")
else
  (cd "$OUT_DIR" && sha256sum "$ZIP_NAME" > "$ZIP_NAME.sha256")
fi

echo "Wrote $ZIP_PATH.sha256"
