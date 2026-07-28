#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required release validation command not found: $1" >&2
    exit 1
  fi
}

for command_name in node git corepack unzip grep basename cat; do
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

VERSION="$(node -p "JSON.parse(require('fs').readFileSync('package.json', 'utf8')).version")"
BACKEND_VERSION="$(
  node -e "const fs = require('fs'); const text = fs.readFileSync('backend/decksoundpad/__init__.py', 'utf8'); const match = text.match(/__version__\\s*=\\s*['\\\"]([^'\\\"]+)['\\\"]/); if (!match) process.exit(2); process.stdout.write(match[1]);"
)"
ZIP_PATH="out/DeckSoundpad-v${VERSION}-full.zip"
CHECKSUM_PATH="${ZIP_PATH}.sha256"
CHECKSUM_NAME="$(basename "$CHECKSUM_PATH")"

if [[ "${DECKSOUNDPAD_REQUIRE_CLEAN_TREE:-0}" == "1" ]]; then
  if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
    echo "Release validation requires a clean git worktree." >&2
    git status --short >&2
    exit 1
  fi
fi

if [[ "${DECKSOUNDPAD_REQUIRE_TAG:-0}" == "1" ]]; then
  TAG_NAME="v${VERSION}"
  HEAD_COMMIT="$(git rev-parse HEAD)"
  TAG_COMMIT="$(git rev-parse -q --verify "refs/tags/${TAG_NAME}^{commit}" || true)"
  if [[ -z "$TAG_COMMIT" ]]; then
    echo "Release validation requires tag ${TAG_NAME} to exist." >&2
    exit 1
  fi
  if [[ "${GITHUB_REF_TYPE:-}" == "tag" && "${GITHUB_REF_NAME:-}" != "$TAG_NAME" ]]; then
    echo "Release validation is running for ${GITHUB_REF_NAME:-unknown}, but package version requires ${TAG_NAME}." >&2
    exit 1
  fi
  if [[ "$TAG_COMMIT" != "$HEAD_COMMIT" ]]; then
    echo "Release validation requires tag ${TAG_NAME} to point at HEAD." >&2
    echo "HEAD: $HEAD_COMMIT" >&2
    echo "${TAG_NAME}: $TAG_COMMIT" >&2
    exit 1
  fi
fi

if [[ "$VERSION" != "$BACKEND_VERSION" ]]; then
  echo "Version mismatch: package.json=$VERSION backend=$BACKEND_VERSION" >&2
  exit 1
fi

node -e "
const fs = require('fs');
const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const plugin = JSON.parse(fs.readFileSync('plugin.json', 'utf8'));
function fail(message) {
  console.error(message);
  process.exit(1);
}
if (pkg.repository && typeof pkg.repository === 'object' && pkg.repository.url === '') {
  fail('package.json repository.url must not be empty');
}
if (pkg.name !== 'decksoundpad' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(pkg.name)) {
  fail('package.json name must be the lowercase Decky package id decksoundpad');
}
if (!/^\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.-]+)?$/.test(pkg.version)) {
  fail('package.json version must be a semver-like release version');
}
if (!pkg.description || pkg.description.length > 140) {
  fail('package.json description must be present and at most 140 characters');
}
if (!pkg.license) fail('package.json license is required');
if (pkg.license !== 'MIT') fail('package.json license must stay MIT');
if (pkg.private !== true) {
  fail('package.json private must remain true; DeckSoundpad is distributed as a Decky/GitHub ZIP artifact, not an npm package');
}
if (!pkg.packageManager || !pkg.packageManager.startsWith('pnpm@9.')) {
  fail('package.json packageManager must pin pnpm 9 for Decky submission compatibility');
}
if (pkg.author !== 'DeckSoundpad contributors') {
  fail('package.json author must be DeckSoundpad contributors until a final public owner is chosen');
}
if (!Array.isArray(pkg.keywords) || pkg.keywords.length < 5) {
  fail('package.json keywords must describe Decky, Steam Deck, audio, and microphone scope');
}
for (const keyword of pkg.keywords || []) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(keyword)) {
    fail('package.json keywords must be lowercase kebab-case values');
  }
}
if (plugin.name !== 'DeckSoundpad') fail('plugin.json name must be DeckSoundpad');
if (plugin.author !== pkg.author) fail('plugin.json author must match package.json author');
if (plugin.api_version !== 1) fail('plugin.json api_version must be 1');
if (!Array.isArray(plugin.flags) || plugin.flags.includes('root')) {
  fail('plugin.json must declare flags as an array without the root flag');
}
if (plugin.flags.includes('debug')) {
  fail('plugin.json must not include the debug flag in release validation');
}
if (!plugin.publish || !Array.isArray(plugin.publish.tags) || !plugin.publish.description) {
  fail('plugin.json publish metadata is incomplete');
}
if (plugin.publish.description.length > 140) {
  fail('plugin.json publish.description must be at most 140 characters');
}
const tags = plugin.publish.tags;
if (tags.length < 3 || tags.length > 8) {
  fail('plugin.json publish.tags must contain 3-8 focused tags');
}
if (new Set(tags).size !== tags.length) {
  fail('plugin.json publish.tags must not contain duplicates');
}
for (const tag of tags) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(tag)) {
    fail('plugin.json publish.tags must be lowercase kebab-case values');
  }
}
for (const requiredTag of ['soundboard', 'audio', 'pipewire', 'microphone']) {
  if (!tags.includes(requiredTag)) fail('plugin.json publish.tags missing required tag: ' + requiredTag);
}
if (process.env.DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE === '1') {
  if (!plugin.publish.image || !/^https:\/\/.+\.png(?:\?.*)?$/i.test(plugin.publish.image)) {
    fail('plugin.json publish.image must be an HTTPS PNG URL for Decky Store submission');
  }
}
"

bash scripts/validate_repo_hygiene.sh
bash scripts/validate_source_archive.sh
bash scripts/validate_deckbrew_submission.sh
corepack pnpm install --frozen-lockfile --ignore-scripts
bash scripts/validate_license_notices.sh
corepack pnpm run check

if grep -nE '__BUILD_DATETIME__|__PACKAGE_VERSION__' dist/index.js >/dev/null; then
  echo "Frontend bundle contains unreplaced build metadata placeholders." >&2
  grep -nE '__BUILD_DATETIME__|__PACKAGE_VERSION__' dist/index.js >&2
  exit 1
fi
if ! grep -Fq "\"${VERSION}\"" dist/index.js; then
  echo "Frontend bundle must include the package version literal in build metadata." >&2
  exit 1
fi
if ! grep -Fq "children: BUILD_METADATA" dist/index.js; then
  echo "Frontend bundle must render build metadata in the Decky panel." >&2
  exit 1
fi

corepack pnpm run scan:secrets
corepack pnpm run package

test -f "$ZIP_PATH"
test -f "$CHECKSUM_PATH"

unzip -l "$ZIP_PATH"
cat "$CHECKSUM_PATH"

ZIP_LIST="$(unzip -Z1 "$ZIP_PATH")"

required_entries=(
  "DeckSoundpad/LICENSE"
  "DeckSoundpad/README.md"
  "DeckSoundpad/SECURITY.md"
  "DeckSoundpad/SUPPORT.md"
  "DeckSoundpad/CHANGELOG.md"
  "DeckSoundpad/RELEASE_MANIFEST.json"
  "DeckSoundpad/plugin.json"
  "DeckSoundpad/package.json"
  "DeckSoundpad/main.py"
  "DeckSoundpad/dist/index.js"
  "DeckSoundpad/defaults/config.default.json"
  "DeckSoundpad/backend/decksoundpad/app.py"
  "DeckSoundpad/backend/decksoundpad/audio_router.py"
  "DeckSoundpad/backend/decksoundpad/audio_player.py"
  "DeckSoundpad/docs/COMPATIBILITY.md"
  "DeckSoundpad/docs/DIAGNOSTICS.md"
  "DeckSoundpad/docs/INSTALLATION.md"
  "DeckSoundpad/docs/PRIVACY.md"
  "DeckSoundpad/docs/THIRD_PARTY_LICENSES.md"
  "DeckSoundpad/docs/THIRD_PARTY_NOTICES.md"
  "DeckSoundpad/docs/TROUBLESHOOTING.md"
)

for entry in "${required_entries[@]}"; do
  if ! grep -Fxq "$entry" <<<"$ZIP_LIST"; then
    echo "Missing required package entry: $entry" >&2
    exit 1
  fi
done

node - "$ZIP_PATH" <<'NODE'
const { execFileSync } = require("child_process");
const path = require("path");

const zipPath = process.argv[2];
const entries = new Set(
  execFileSync("unzip", ["-Z1", zipPath], { encoding: "utf8" })
    .split(/\r?\n/)
    .filter(Boolean),
);
const failures = [];
const linkPattern = /!?\[[^\]]*\]\(([^)]+)\)/g;

for (const entry of entries) {
  if (!entry.toLowerCase().endsWith(".md")) continue;
  const markdown = execFileSync("unzip", ["-p", zipPath, entry], {
    encoding: "utf8",
  });
  for (const match of markdown.matchAll(linkPattern)) {
    let target = match[1].trim();
    const wrapped = target.match(/^<([^>]+)>/);
    if (wrapped) {
      target = wrapped[1];
    } else {
      target = target.split(/\s+["']/)[0];
    }
    if (!target || target.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(target)) {
      continue;
    }
    target = target.split(/[?#]/, 1)[0];
    try {
      target = decodeURIComponent(target);
    } catch {
      failures.push(`${entry}: invalid encoded link target ${match[1]}`);
      continue;
    }
    const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(entry), target));
    if (resolved.startsWith("../") || !entries.has(resolved)) {
      failures.push(`${entry}: missing relative link target ${target}`);
    }
  }
}

if (failures.length > 0) {
  console.error("Packaged Markdown link validation failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}
console.log("Packaged Markdown link validation passed.");
NODE

MANIFEST_JSON="$(unzip -p "$ZIP_PATH" DeckSoundpad/RELEASE_MANIFEST.json)"
node -e "
const fs = require('fs');
const manifest = JSON.parse(process.argv[1]);
const expectedVersion = process.argv[2];
const expectedArtifact = process.argv[3];
const expectedCommit = process.argv[4];
const expectedDirty = process.argv[5] === 'true';
const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const plugin = JSON.parse(fs.readFileSync('plugin.json', 'utf8'));
function fail(message) {
  console.error(message);
  process.exit(1);
}
if (manifest.name !== 'DeckSoundpad') fail('release manifest name mismatch');
if (manifest.packageName !== pkg.name) fail('release manifest packageName mismatch');
if (manifest.version !== expectedVersion) fail('release manifest version mismatch');
if (manifest.backendVersion !== expectedVersion) fail('release manifest backendVersion mismatch');
if (manifest.artifact !== expectedArtifact) fail('release manifest artifact mismatch');
if (manifest.apiVersion !== plugin.api_version) fail('release manifest apiVersion mismatch');
if (!Array.isArray(manifest.flags)) fail('release manifest flags must be an array');
const manifestFlags = [...manifest.flags].sort();
const pluginFlags = [...(plugin.flags || [])].sort();
if (JSON.stringify(manifestFlags) !== JSON.stringify(pluginFlags)) {
  fail('release manifest flags must match plugin.json flags');
}
if (!manifest.sourceCommit || !/^[0-9a-f]{40}$/.test(manifest.sourceCommit)) {
  fail('release manifest must include a 40-character git source commit');
}
if (manifest.sourceCommit !== expectedCommit) fail('release manifest sourceCommit must match HEAD');
if (typeof manifest.sourceDirty !== 'boolean') fail('release manifest sourceDirty must be boolean');
if (manifest.sourceDirty !== expectedDirty) fail('release manifest sourceDirty must match current git status');
if (!manifest.generatedAt || Number.isNaN(Date.parse(manifest.generatedAt))) {
  fail('release manifest generatedAt must be an ISO-like timestamp');
}
" "$MANIFEST_JSON" "$VERSION" "$(basename "$ZIP_PATH")" "$(git rev-parse HEAD)" "$([[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]] && echo true || echo false)"

forbidden_pattern='(^|/)(node_modules|backend/tests|src|\.git|\.github|out|\.pnpm-store|\.tmp-run|__pycache__)(/|$)|\.py[cod]$|\.map$|\.log$|\.DS_Store$'
if grep -Eq "$forbidden_pattern" <<<"$ZIP_LIST"; then
  echo "Forbidden development artifact found in package:" >&2
  grep -E "$forbidden_pattern" <<<"$ZIP_LIST" >&2
  exit 1
fi

docs_media_pattern='^DeckSoundpad/docs/(assets/|.*\.(png|jpg|jpeg|gif|webp|webm|mp4|mov|mkv)$)'
if grep -Eiq "$docs_media_pattern" <<<"$ZIP_LIST"; then
  echo "Release media must not be bundled into the runtime plugin ZIP:" >&2
  grep -Ei "$docs_media_pattern" <<<"$ZIP_LIST" >&2
  exit 1
fi

if grep -Eq '^/' "$CHECKSUM_PATH"; then
  echo "Checksum file must use a relative artifact filename, not an absolute path" >&2
  exit 1
fi

if [[ "$CHECKSUM_TOOL" == "shasum" ]]; then
  (cd out && shasum -a 256 -c "$CHECKSUM_NAME")
else
  (cd out && sha256sum -c "$CHECKSUM_NAME")
fi

echo "Release validation passed for $ZIP_PATH"
