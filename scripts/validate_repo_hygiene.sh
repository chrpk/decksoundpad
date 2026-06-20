#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

required_files=(
  "README.md"
  ".editorconfig"
  ".gitignore"
  ".gitattributes"
  "LICENSE"
  "CONTRIBUTING.md"
  "SECURITY.md"
  "SUPPORT.md"
  "CODE_OF_CONDUCT.md"
  "CHANGELOG.md"
  ".github/PULL_REQUEST_TEMPLATE.md"
  ".github/ISSUE_TEMPLATE/bug_report.yml"
  ".github/ISSUE_TEMPLATE/feature_request.yml"
  ".github/ISSUE_TEMPLATE/release_checklist.yml"
  ".github/ISSUE_TEMPLATE/config.yml"
  ".github/labels.yml"
  ".github/dependabot.yml"
  ".github/workflows/ci.yml"
  ".github/workflows/codeql.yml"
  ".github/workflows/dependency-review.yml"
  ".github/workflows/release.yml"
  ".github/workflows/secret-scan.yml"
  "docs/ARCHITECTURE.md"
  "docs/BRIDGE_API.md"
  "docs/COMPATIBILITY.md"
  "docs/DECKBREW_SUBMISSION_CHECKLIST.md"
  "docs/DECKBREW_SUBMISSION_EVIDENCE.md"
  "docs/DIAGNOSTICS.md"
  "docs/EXTERNAL_OVERLAY_POC.md"
  "docs/HARDWARE_VALIDATION.md"
  "docs/INSTALLATION.md"
  "docs/MAINTAINER_GUIDE.md"
  "docs/OPEN_SOURCE_READINESS.md"
  "docs/PRIVACY.md"
  "docs/PUBLICATION_RUNBOOK.md"
  "docs/REFERENCE_REPOS.md"
  "docs/REPOSITORY_SETTINGS.md"
  "docs/RELEASE_ASSETS.md"
  "docs/RELEASE_NOTES_TEMPLATE.md"
  "docs/ROOT_PERMISSION_RATIONALE.md"
  "docs/STEAMDECK_AUDIO_POC.md"
  "docs/THREAT_MODEL.md"
  "docs/THIRD_PARTY_LICENSES.md"
  "docs/THIRD_PARTY_NOTICES.md"
  "docs/TROUBLESHOOTING.md"
  "rollup.config.js"
  "scripts/validate_source_archive.sh"
  "scripts/validate_publication_readiness.sh"
  "scripts/validate_deckbrew_submission.sh"
  "src/buildInfo.ts"
  "tsconfig.json"
)

for file in "${required_files[@]}"; do
  if [[ ! -s "$file" ]]; then
    echo "Required repository hygiene file is missing or empty: $file" >&2
    exit 1
  fi
done

for script in scripts/*.sh; do
  if [[ "$(head -n 1 "$script")" != "#!/usr/bin/env bash" ]]; then
    echo "Shell script must use the bash env shebang: $script" >&2
    exit 1
  fi
  if ! grep -qx "set -euo pipefail" "$script"; then
    echo "Shell script must enable set -euo pipefail: $script" >&2
    exit 1
  fi
  bash -n "$script"
done

DRY_RUN=1 bash scripts/sync_labels.sh >/dev/null

node <<'NODE'
const fs = require("fs");
const path = require("path");

function fail(message) {
  console.error(message);
  process.exit(1);
}

function read(path) {
  return fs.readFileSync(path, "utf8");
}

const labelText = read(".github/labels.yml");
const labels = new Set();
for (const line of labelText.split(/\r?\n/)) {
  const match = line.match(/^- name:\s*(.+)$/);
  if (match) labels.add(match[1].trim());
}
if (labels.size === 0) fail(".github/labels.yml must define at least one label");
for (const requiredLabel of [
  "bug",
  "documentation",
  "enhancement",
  "security",
  "audio-routing",
  "steam-deck",
  "external-overlay",
  "sound-library",
  "packaging",
  "dependencies",
  "good-first-issue",
]) {
  if (!labels.has(requiredLabel)) {
    fail(`.github/labels.yml missing required label: ${requiredLabel}`);
  }
}

for (const template of [
  ".github/ISSUE_TEMPLATE/bug_report.yml",
  ".github/ISSUE_TEMPLATE/feature_request.yml",
  ".github/ISSUE_TEMPLATE/release_checklist.yml",
]) {
  const text = read(template);
  const declared = [];
  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index] !== "labels:") continue;
    for (let next = index + 1; next < lines.length; next += 1) {
      const item = lines[next].match(/^\s{2}-\s*(.+)$/);
      if (!item) break;
      declared.push(item[1].trim());
    }
  }
  if (declared.length === 0) fail(`${template} must declare at least one default label`);
  for (const label of declared) {
    if (!labels.has(label)) fail(`${template} references undefined label: ${label}`);
  }
}

const issueConfig = read(".github/ISSUE_TEMPLATE/config.yml");
if (!/^blank_issues_enabled:\s*false\s*$/m.test(issueConfig)) {
  fail(".github/ISSUE_TEMPLATE/config.yml must disable blank issues so public reports use the redaction and diagnostics templates");
}

const bugReportTemplate = read(".github/ISSUE_TEMPLATE/bug_report.yml");
for (const requiredText of [
  "Do not include private security details, exploit steps, private paths, usernames, or unredacted logs in public issues.",
  "Use SECURITY.md for vulnerability reports",
  "docs/DIAGNOSTICS.md",
  "id: deck-model",
  "Steam Deck model",
  "id: install-source",
  "Installation source",
  "I did not include private security details, exploit steps, private paths, usernames, or unredacted logs in this public issue.",
  "I redacted local usernames, private paths, device names, and unrelated log lines.",
  "required: true",
]) {
  if (!bugReportTemplate.includes(requiredText)) {
    fail(`.github/ISSUE_TEMPLATE/bug_report.yml must include public-report safety text: ${requiredText}`);
  }
}

const featureRequestTemplate = read(".github/ISSUE_TEMPLATE/feature_request.yml");
for (const requiredText of [
  "Do not use public feature requests for vulnerability reports, exploit details, private paths, usernames, or unredacted logs.",
  "Use SECURITY.md for vulnerability reports.",
  "id: public-safety",
  "I did not include vulnerability details, exploit steps, private paths, usernames, or unredacted logs in this public request.",
  "required: true",
]) {
  if (!featureRequestTemplate.includes(requiredText)) {
    fail(`.github/ISSUE_TEMPLATE/feature_request.yml must include public-report safety text: ${requiredText}`);
  }
}

const requiredValidationCommands = [
  "corepack pnpm run check",
  "corepack pnpm run validate:repo",
  "corepack pnpm run validate:deckbrew",
  "corepack pnpm run validate:source-archive",
  "corepack pnpm run validate:licenses",
  "corepack pnpm run scan:secrets",
  "corepack pnpm run validate:release",
];
const pullRequestTemplate = read(".github/PULL_REQUEST_TEMPLATE.md");
for (const command of requiredValidationCommands) {
  if (!pullRequestTemplate.includes(command)) {
    fail(`.github/PULL_REQUEST_TEMPLATE.md must include validation command: ${command}`);
  }
}
for (const requiredText of [
  "## Dependency And Notice Review",
  "corepack pnpm run licenses:generate",
  "dependency versions, source imports, or icon imports changed",
  "docs/THIRD_PARTY_NOTICES.md",
  "docs/THIRD_PARTY_LICENSES.md",
]) {
  if (!pullRequestTemplate.includes(requiredText)) {
    fail(`.github/PULL_REQUEST_TEMPLATE.md must include dependency notice review text: ${requiredText}`);
  }
}
const releaseChecklist = read(".github/ISSUE_TEMPLATE/release_checklist.yml");
for (const command of [
  "corepack pnpm install --frozen-lockfile",
  ...requiredValidationCommands,
  "corepack pnpm run package",
]) {
  if (!releaseChecklist.includes(command)) {
    fail(`.github/ISSUE_TEMPLATE/release_checklist.yml must include validation command: ${command}`);
  }
}
if (!releaseChecklist.includes("`CodeQL` workflow passed or reviewed for this release candidate")) {
  fail(".github/ISSUE_TEMPLATE/release_checklist.yml must require CodeQL review for release candidates");
}
if (!releaseChecklist.includes("`Dependency Review` workflow passed for dependency changes")) {
  fail(".github/ISSUE_TEMPLATE/release_checklist.yml must require Dependency Review for dependency changes");
}
if (!releaseChecklist.includes("`corepack pnpm run validate:publication` passed after external evidence was supplied")) {
  fail(".github/ISSUE_TEMPLATE/release_checklist.yml must require validate:publication after external evidence");
}
const contributing = read("CONTRIBUTING.md");
for (const command of requiredValidationCommands) {
  if (!contributing.includes(command)) {
    fail(`CONTRIBUTING.md must include validation command: ${command}`);
  }
}
if (!contributing.includes("corepack pnpm run validate:publication")) {
  fail("CONTRIBUTING.md must include the final publication readiness command");
}
if (!contributing.includes("docs/ARCHITECTURE.md")) {
  fail("CONTRIBUTING.md must point contributors to docs/ARCHITECTURE.md before architecture-sensitive changes");
}
if (!contributing.includes("docs/BRIDGE_API.md")) {
  fail("CONTRIBUTING.md must point contributors to docs/BRIDGE_API.md before bridge callable changes");
}
for (const requiredText of [
  "CodeQL workflow enabled",
  "JavaScript/TypeScript and Python code scanning",
  "every new alert has been triaged",
  "Dependency Review workflow enabled",
  "request introduces moderate-or-higher vulnerable dependencies",
]) {
  if (!contributing.includes(requiredText)) {
    fail(`CONTRIBUTING.md must include security workflow guidance: ${requiredText}`);
  }
}

const releaseNotesTemplate = read("docs/RELEASE_NOTES_TEMPLATE.md");
for (const requiredText of [
  "Checksum: `<sha256>  DeckSoundpad-vX.Y.Z-full.zip`",
  "exact uploaded ZIP from the tagged release workflow",
  "docs/INSTALLATION.md",
  "generatedAt",
  "Tagged Release Artifact workflow",
  "Full-history secret scan",
  "Publication readiness gate",
  "\"sourceDirty\": false",
  "Decky Store image",
  "SECURITY.md",
]) {
  if (!releaseNotesTemplate.includes(requiredText)) {
    fail(`docs/RELEASE_NOTES_TEMPLATE.md must include release evidence text: ${requiredText}`);
  }
}

const architecture = read("docs/ARCHITECTURE.md");
for (const requiredText of [
  "Runtime Shape",
  "Entry Points",
  "Frontend Modules",
  "Backend Modules",
  "Main Data Flows",
  "Library Scanning",
  "Playback And Audio Routing",
  "External Overlay",
  "Local Files And Logs",
  "Privileged Behavior",
  "Simulation And Tests",
  "Build And Release Artifacts",
  "Change Review Checklist",
  "src/index.tsx",
  "src/api/decky.ts",
  "main.py",
  "backend/decksoundpad/app.py",
  "backend/decksoundpad/audio_router.py",
  "backend/decksoundpad/audio_player.py",
  "backend/decksoundpad/library.py",
  "backend/decksoundpad/external_overlay.py",
  "docs/ROOT_PERMISSION_RATIONALE.md",
  "docs/BRIDGE_API.md",
  "docs/HARDWARE_VALIDATION.md",
  "scripts/validate_release.sh",
  "RELEASE_MANIFEST.json",
  "must not add a LAN HTTP API",
]) {
  if (!architecture.includes(requiredText)) {
    fail(`docs/ARCHITECTURE.md must include architecture/code map guidance: ${requiredText}`);
  }
}

const bridgeApi = read("docs/BRIDGE_API.md");
for (const requiredText of [
  "Decky Bridge API",
  "src/api/decky.ts",
  "src/types.ts",
  "main.py",
  "backend/decksoundpad/app.py",
  "backend/tests/test_main_bridge.py",
  "get_status",
  "start_backend",
  "refresh_library",
  "repair_audio",
  "get_settings",
  "update_settings",
  "DeckSoundpadStatus",
  "LibraryRefreshResponse",
  "Settings",
  "`play_sound` is not a public frontend bridge callable",
  "backend_running: false",
  "state: \"offline\"",
  "corepack pnpm run validate:release",
]) {
  if (!bridgeApi.includes(requiredText)) {
    fail(`docs/BRIDGE_API.md must include Decky bridge contract guidance: ${requiredText}`);
  }
}

const publicationRunbook = read("docs/PUBLICATION_RUNBOOK.md");
for (const requiredText of [
  "docs/REPOSITORY_SETTINGS.md",
  "docs/DECKBREW_SUBMISSION_CHECKLIST.md",
  "docs/DECKBREW_SUBMISSION_EVIDENCE.md",
  "docs/INSTALLATION.md",
  "corepack pnpm run validate:publication",
  "DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION",
  "DECKSOUNDPAD_HARDWARE_VALIDATION_EVIDENCE",
  "exact uploaded ZIP",
  "later local rebuild",
  "RELEASE_MANIFEST.json",
  "generatedAt",
]) {
  if (!publicationRunbook.includes(requiredText)) {
    fail(`docs/PUBLICATION_RUNBOOK.md must include checksum provenance text: ${requiredText}`);
  }
}

const installationGuide = read("docs/INSTALLATION.md");
for (const requiredText of [
  "Install From A Release ZIP",
  "Update",
  "Roll Back",
  "Uninstall",
  "Local Data To Review",
  "Recovery",
  "Verify that the checksum",
  "visible version/build metadata",
  "~/Music/DeckSoundpad",
  "~/Public/DeckSoundpad/logs/",
  "should not delete those files",
  "should not require deleting your sound library",
  "RELEASE_MANIFEST.json",
]) {
  if (!installationGuide.includes(requiredText)) {
    fail(`docs/INSTALLATION.md must include install/update/removal guidance: ${requiredText}`);
  }
}

const repositorySettings = read("docs/REPOSITORY_SETTINGS.md");
for (const requiredText of [
  "Default workflow token permissions: read-only",
  "Dependency graph",
  "Dependabot alerts",
  "Code scanning alerts",
  "Secret scanning and push protection",
  "Private vulnerability reporting",
  "`CI`",
  "`CodeQL`",
  "`Dependency Review`",
  "`Secret Scan`",
  "`Tagged Release Artifact`",
  "Protect release tags matching `v*`",
  "corepack pnpm run validate:repo",
  "corepack pnpm run validate:release",
  "corepack pnpm run validate:publication",
  "Steam Deck hardware validation evidence",
]) {
  if (!repositorySettings.includes(requiredText)) {
    fail(`docs/REPOSITORY_SETTINGS.md must include public repository settings baseline text: ${requiredText}`);
  }
}

const publicationReadiness = read("scripts/validate_publication_readiness.sh");
for (const requiredText of [
  "DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION",
  "DECKSOUNDPAD_PUBLIC_REPOSITORY_EVIDENCE",
  "DECKSOUNDPAD_LLM_CODE_PROVENANCE_EVIDENCE",
  "DECKSOUNDPAD_DECKBREW_DATABASE_PR_EVIDENCE",
  "DECKSOUNDPAD_DECKBREW_STEAMOS_TEST_EVIDENCE",
  "DECKSOUNDPAD_REPOSITORY_SETTINGS_APPLIED",
  "DECKSOUNDPAD_PRIVATE_VULN_REPORTING_CONFIRMED",
  "DECKSOUNDPAD_SECURITY_CONTACT_EVIDENCE",
  "DECKSOUNDPAD_FULL_HISTORY_SECRET_SCAN_EVIDENCE",
  "DECKSOUNDPAD_HARDWARE_VALIDATION_EVIDENCE",
  "DECKSOUNDPAD_RELEASE_MEDIA_EVIDENCE",
  "DECKSOUNDPAD_RELEASE_ARTIFACT_EVIDENCE",
  "DECKSOUNDPAD_RELEASE_CHECKSUM_EVIDENCE",
  "DECKSOUNDPAD_CI_RUN_EVIDENCE",
  "DECKSOUNDPAD_CODEQL_RUN_EVIDENCE",
  "DECKSOUNDPAD_DEPENDENCY_REVIEW_RUN_EVIDENCE",
  "DECKSOUNDPAD_SECRET_SCAN_RUN_EVIDENCE",
  "DECKSOUNDPAD_TAGGED_ARTIFACT_RUN_EVIDENCE",
  "DECKSOUNDPAD_MIN_STEAMOS_VERSION",
  "DECKSOUNDPAD_MIN_DECKY_LOADER_VERSION",
  "DECKSOUNDPAD_ROOT_FLAG_DECISION",
  "corepack pnpm run validate:release",
]) {
  if (!publicationReadiness.includes(requiredText)) {
    fail(`scripts/validate_publication_readiness.sh must enforce public publication evidence: ${requiredText}`);
  }
}

const rollupConfig = read("rollup.config.js");
for (const requiredText of [
  'fs.readFileSync(new URL("./package.json", import.meta.url)',
  "__PACKAGE_VERSION__",
  "__BUILD_DATETIME__",
  "decksoundpad-build-metadata",
]) {
  if (!rollupConfig.includes(requiredText)) {
    fail(`rollup.config.js must inject build metadata into the frontend bundle: ${requiredText}`);
  }
}

const buildInfo = read("src/buildInfo.ts");
for (const requiredText of [
  "__PACKAGE_VERSION__",
  "__BUILD_DATETIME__",
  "BUILD_METADATA",
  "v${version} | Build ${dateTime}",
]) {
  if (!buildInfo.includes(requiredText)) {
    fail(`src/buildInfo.ts must expose package version and build timestamp metadata: ${requiredText}`);
  }
}

const frontendEntry = read("src/index.tsx");
for (const requiredText of [
  "BUILD_METADATA",
  "<div style={topBuildMetaStyle}>{BUILD_METADATA}</div>",
]) {
  if (!frontendEntry.includes(requiredText)) {
    fail(`src/index.tsx must render build metadata for diagnostics and hardware validation: ${requiredText}`);
  }
}

const licenseValidation = read("scripts/validate_license_notices.sh");
for (const requiredText of [
  "corepack\", [\"pnpm\", \"licenses\", \"list\", ...args]",
  "collectImportedPackageNames()",
  "scripts/generate_third_party_licenses.sh",
  "docs/THIRD_PARTY_LICENSES.md",
  "stale or unexpected production dependency notice row",
  "stale or unexpected direct development dependency notice row",
  "sectionBacktickBullets(\"Transitive License Families Observed\")",
  "stale or unexpected transitive license family",
  "stale or unexpected direct development dependency version/license row",
  "sectionSourceAvailabilityRows()",
  "LGPL Source Availability",
  "No local third-party source modifications",
  "upstreamSourceUrlForPackage(",
  "stale or unexpected LGPL source availability row",
  "collectReactIconsFaImports()",
  "react-icons/fa",
  "Font Awesome",
  "CC BY 4.0",
  "src",
  "pkg.devDependencies",
  "platform-specific direct development dependency",
]) {
  if (!licenseValidation.includes(requiredText)) {
    fail(`scripts/validate_license_notices.sh must cover source-imported and direct development dependencies: ${requiredText}`);
  }
}

const codeOfConduct = read("CODE_OF_CONDUCT.md");
for (const requiredText of [
  "## Scope",
  "## Expected Behavior",
  "## Unacceptable Behavior",
  "## Enforcement And Reporting",
  "harassment",
  "private information",
  "restrict",
  "private reporting channel",
  "minimal public issue",
  "SECURITY.md",
]) {
  if (!codeOfConduct.includes(requiredText)) {
    fail(`CODE_OF_CONDUCT.md must include conduct policy text: ${requiredText}`);
  }
}

const securityPolicy = read("SECURITY.md");
for (const requiredText of [
  "## Static Analysis",
  "CodeQL workflow",
  "JavaScript/TypeScript and Python",
  "Review CodeQL alerts before tagging releases",
  "## Supply Chain Review",
  "Dependency Review workflow",
  "moderate-or-higher vulnerable",
]) {
  if (!securityPolicy.includes(requiredText)) {
    fail(`SECURITY.md must include static analysis and supply-chain guidance: ${requiredText}`);
  }
}

const maintainerGuide = read("docs/MAINTAINER_GUIDE.md");
for (const requiredText of [
  "docs/ARCHITECTURE.md",
  "corepack pnpm run validate:source-archive",
  "the `CodeQL` workflow passed",
  "code scanning alert has been",
  "the `Dependency Review` workflow passed for dependency changes",
  "moderate-or-higher vulnerable dependency",
]) {
  if (!maintainerGuide.includes(requiredText)) {
    fail(`docs/MAINTAINER_GUIDE.md must include security/source-archive maintainer guidance: ${requiredText}`);
  }
}

const threatModel = read("docs/THREAT_MODEL.md");
if (!threatModel.includes("docs/ARCHITECTURE.md")) {
  fail("docs/THREAT_MODEL.md must point reviewers to docs/ARCHITECTURE.md");
}

const basicSecretScan = read("scripts/basic_secret_scan.sh");
for (const requiredText of [
  "git ls-files -z --cached --others --exclude-standard",
  "grep -nEI -e",
  "git log --all -p -- . | grep -nE -e",
  "Scanning current tracked and untracked source files",
  "glpat-[A-Za-z0-9_-]{20,}",
  "npm_[A-Za-z0-9]{30,}",
  "sk-(proj-)?[A-Za-z0-9_-]{32,}",
  "sk_live_[A-Za-z0-9]{24,}",
]) {
  if (!basicSecretScan.includes(requiredText)) {
    fail(`scripts/basic_secret_scan.sh must scan untracked publication files: ${requiredText}`);
  }
}
if (/pnpm-lock\.yaml[\s\S]{0,120}continue/.test(basicSecretScan)) {
  fail("scripts/basic_secret_scan.sh must scan pnpm-lock.yaml because lockfiles can contain private registry or git URLs");
}
if (basicSecretScan.includes("git grep")) {
  fail("scripts/basic_secret_scan.sh must not rely on git grep for current-file scanning because git grep skips untracked publication files");
}
if (basicSecretScan.includes("rg ")) {
  fail("scripts/basic_secret_scan.sh must not require undeclared ripgrep for release validation");
}

const packagePlugin = read("scripts/package_plugin.sh");
for (const requiredText of [
  "require_command()",
  "for command_name in bash node corepack git zip find cp rm mkdir mv basename mktemp; do",
  "bash scripts/validate_license_notices.sh",
  "Required checksum command not found: install shasum or sha256sum",
  "CHECKSUM_TOOL=\"shasum\"",
  "CHECKSUM_TOOL=\"sha256sum\"",
  "cp -R backend/decksoundpad",
  "find \"$PLUGIN_DIR/backend/decksoundpad\" -type d -name __pycache__",
  "find \"$PLUGIN_DIR/backend/decksoundpad\" -type f \\( -name '*.pyc' -o -name '*.pyo' -o -name '*.pyd' \\)",
  "-x '*.pyc'",
  "-x '*.pyo'",
  "-x '*.pyd'",
]) {
  if (!packagePlugin.includes(requiredText)) {
    fail(`scripts/package_plugin.sh must keep portable packaging command coverage: ${requiredText}`);
  }
}
if (packagePlugin.includes("rsync")) {
  fail("scripts/package_plugin.sh must not require rsync for release packaging");
}
if (packagePlugin.includes("Warning: no SHA-256 checksum tool found")) {
  fail("scripts/package_plugin.sh must fail when no SHA-256 checksum tool is available");
}
if (packagePlugin.indexOf("for command_name in bash node corepack git zip find cp rm mkdir mv basename mktemp; do") > packagePlugin.indexOf("VERSION=")) {
  fail("scripts/package_plugin.sh must preflight packaging commands before reading package metadata with node");
}
if (packagePlugin.indexOf("Required checksum command not found: install shasum or sha256sum") > packagePlugin.indexOf("VERSION=")) {
  fail("scripts/package_plugin.sh must preflight checksum commands before reading package metadata with node");
}
if (packagePlugin.indexOf("bash scripts/validate_license_notices.sh") > packagePlugin.indexOf("VERSION=")) {
  fail("scripts/package_plugin.sh must validate third-party license notices before reading package metadata and staging an artifact");
}

const releaseValidation = read("scripts/validate_release.sh");
for (const requiredText of [
  "require_command()",
  "for command_name in node git corepack unzip grep basename cat; do",
  "Required checksum command not found: install shasum or sha256sum",
  "CHECKSUM_TOOL=\"shasum\"",
  "CHECKSUM_TOOL=\"sha256sum\"",
  "bash scripts/validate_source_archive.sh",
  "bash scripts/validate_deckbrew_submission.sh",
  "dist/index.js",
  "__BUILD_DATETIME__|__PACKAGE_VERSION__",
  "grep -Fq \"\\\"${VERSION}\\\"\" dist/index.js",
  "children: BUILD_METADATA",
  "Frontend bundle must include the package version literal in build metadata.",
  "Frontend bundle must render build metadata in the Decky panel.",
  "\\.py[cod]$",
]) {
  if (!releaseValidation.includes(requiredText)) {
    fail(`scripts/validate_release.sh must preflight required commands: ${requiredText}`);
  }
}
if (releaseValidation.indexOf("for command_name in node git corepack unzip grep basename cat; do") > releaseValidation.indexOf("VERSION=")) {
  fail("scripts/validate_release.sh must preflight release commands before reading package metadata with node");
}
if (releaseValidation.indexOf("Required checksum command not found: install shasum or sha256sum") > releaseValidation.indexOf("VERSION=")) {
  fail("scripts/validate_release.sh must preflight checksum commands before reading package metadata with node");
}

const sourceArchiveValidation = read("scripts/validate_source_archive.sh");
for (const requiredText of [
  "[\"ls-files\", \"-z\", \"--cached\", \"--others\", \"--exclude-standard\"]",
  "[\"check-attr\", \"-z\", \"export-ignore\", \"--\", file]",
  "Required source archive file is missing",
  "Source archive policy would include forbidden local/generated files",
  "node_modules|\\.pnpm-store",
  "dist|out|backend\\/out|htmlcov",
  "scripts/validate_source_archive.sh",
]) {
  if (!sourceArchiveValidation.includes(requiredText)) {
    fail(`scripts/validate_source_archive.sh must enforce source archive policy: ${requiredText}`);
  }
}

for (const template of [
  ".github/PULL_REQUEST_TEMPLATE.md",
  ".github/ISSUE_TEMPLATE/bug_report.yml",
  ".github/ISSUE_TEMPLATE/feature_request.yml",
  ".github/ISSUE_TEMPLATE/release_checklist.yml",
  ".github/ISSUE_TEMPLATE/config.yml",
]) {
  const text = read(template);
  const refPattern = /(?:^|[\s`'"])((?:docs|\.github|scripts)\/[A-Za-z0-9._/-]+|(?:README|SECURITY|SUPPORT|CONTRIBUTING|CHANGELOG|CODE_OF_CONDUCT|LICENSE)(?:\.md)?)(?=[\s`'",;:)\]]|$)/gm;
  for (const match of text.matchAll(refPattern)) {
    const target = match[1];
    if (!fs.existsSync(target)) {
      fail(`${template} references missing local file: ${target}`);
    }
  }
}

const workflowFiles = fs.readdirSync(".github/workflows")
  .filter((name) => name.endsWith(".yml") || name.endsWith(".yaml"))
  .map((name) => path.join(".github/workflows", name));
if (workflowFiles.length === 0) fail(".github/workflows must define at least one workflow");

const nvmrc = read(".nvmrc").trim();
if (nvmrc !== "22") {
  fail(".nvmrc must pin Node 22 to match CI and release validation");
}

const requiredActionPins = new Map([
  ["actions/checkout", "v7"],
  ["actions/setup-node", "v6"],
  ["actions/setup-python", "v6"],
  ["actions/upload-artifact", "v7"],
  ["actions/dependency-review-action", "v5"],
  ["pnpm/action-setup", "v6"],
  ["github/codeql-action/init", "v4"],
  ["github/codeql-action/analyze", "v4"],
  ["gitleaks/gitleaks-action", "v3"],
]);

for (const workflow of workflowFiles) {
  const text = read(workflow);
  if (text.includes("pull_request_target:")) {
    fail(`${workflow} must not use pull_request_target for untrusted contribution workflows`);
  }
  for (const line of text.split(/\r?\n/)) {
    const action = line.match(/^\s+uses:\s+([^@\s]+)(?:@([^\s]+))?\s*$/);
    if (!action) continue;
    const [, name, version] = action;
    if (!version) fail(`${workflow} must pin GitHub Action ${name} to an explicit version`);
    const requiredVersion = requiredActionPins.get(name);
    if (requiredVersion && version !== requiredVersion) {
      fail(`${workflow} must use ${name}@${requiredVersion}`);
    }
  }
  const isCodeqlWorkflow = workflow.endsWith("/codeql.yml") || workflow.endsWith("/codeql.yaml");
  const isDependencyReviewWorkflow = workflow.endsWith("/dependency-review.yml") || workflow.endsWith("/dependency-review.yaml");
  const isReleaseWorkflow = workflow.endsWith("/release.yml") || workflow.endsWith("/release.yaml");
  if (isCodeqlWorkflow) {
    if (!/^permissions:\n\s+contents:\s+read\n\s+security-events:\s+write$/m.test(text)) {
      fail(`${workflow} must grant only contents: read and security-events: write for CodeQL result upload`);
    }
  } else if (isReleaseWorkflow) {
    if (!/^permissions:\n\s+contents:\s+write$/m.test(text)) {
      fail(`${workflow} must grant contents: write so it can publish GitHub Release assets`);
    }
  } else if (!/^permissions:\n\s+contents:\s+read$/m.test(text)) {
    fail(`${workflow} must set read-only contents permissions`);
  }
  if (!isCodeqlWorkflow && text.includes("security-events: write")) {
    fail(`${workflow} must not request security-events: write outside the CodeQL workflow`);
  }
  if (!isReleaseWorkflow && text.includes("contents: write")) {
    fail(`${workflow} must not request contents: write outside the release publishing workflow`);
  }
  if (text.includes("pull-requests: write")) {
    fail(`${workflow} must not request pull-requests: write; dependency review PR comments stay disabled`);
  }
  if (!/^concurrency:/m.test(text)) {
    fail(`${workflow} must define concurrency to avoid stale duplicate runs`);
  }
  if (!/^\s+timeout-minutes:\s+\d+$/m.test(text)) {
    fail(`${workflow} must set a job timeout`);
  }
  if (text.includes("actions/checkout") && !/^\s+persist-credentials:\s+false\s*$/m.test(text)) {
    fail(`${workflow} must disable checkout credential persistence`);
  }
  if (text.includes("actions/setup-node")) {
    const nodeVersion = text.match(/^\s+node-version:\s+["']?([^"'\n]+)["']?\s*$/m);
    if (!nodeVersion || nodeVersion[1] !== nvmrc) {
      fail(`${workflow} must use node-version ${nvmrc} to match .nvmrc`);
    }
    if (!/^\s+cache:\s+pnpm\s*$/m.test(text)) {
      fail(`${workflow} must enable pnpm dependency caching when using setup-node`);
    }
    if (!/^\s+cache-dependency-path:\s+pnpm-lock\.yaml\s*$/m.test(text)) {
      fail(`${workflow} must bind setup-node pnpm caching to pnpm-lock.yaml`);
    }
    if (!text.includes("uses: pnpm/action-setup@v6")) {
      fail(`${workflow} must set up pnpm before setup-node so pnpm cache restore has a pnpm executable`);
    }
    if (text.indexOf("uses: pnpm/action-setup@v6") > text.indexOf("uses: actions/setup-node@v6")) {
      fail(`${workflow} must run pnpm/action-setup before actions/setup-node when setup-node cache is pnpm`);
    }
    if (!/^\s+version:\s+9\.15\.9\s*$/m.test(text)) {
      fail(`${workflow} must pin pnpm/action-setup to pnpm 9.15.9`);
    }
    if (!/^\s+run_install:\s+false\s*$/m.test(text)) {
      fail(`${workflow} must keep pnpm/action-setup from installing dependencies outside validate:release`);
    }
  }
  if (text.includes("actions/upload-artifact")) {
    if (!text.includes("DECKSOUNDPAD_VERSION")) {
      fail(`${workflow} must derive the uploaded package version from package.json`);
    }
    for (const expectedPath of [
      "out/DeckSoundpad-v${{ env.DECKSOUNDPAD_VERSION }}-full.zip",
      "out/DeckSoundpad-v${{ env.DECKSOUNDPAD_VERSION }}-full.zip.sha256",
    ]) {
      if (!text.includes(expectedPath)) {
        fail(`${workflow} must upload exact current-version artifact path: ${expectedPath}`);
      }
    }
    if (/out\/DeckSoundpad-v\*-full\.zip/.test(text)) {
      fail(`${workflow} must not upload release artifacts using broad version wildcards`);
    }
  }
  if (isReleaseWorkflow) {
    for (const requiredText of [
      "workflow_dispatch:",
      "publish_release:",
      "DECKSOUNDPAD_REQUIRE_TAG: \"1\"",
      "DECKSOUNDPAD_TAG=v$VERSION",
      "gh release view",
      "gh release upload",
      "gh release create",
      "--verify-tag",
      "--generate-notes",
      "--clobber",
    ]) {
      if (!text.includes(requiredText)) {
        fail(`${workflow} must support GitHub release package publishing: ${requiredText}`);
      }
    }
  }
  if (isCodeqlWorkflow) {
    for (const requiredText of [
      "github/codeql-action/init@v4",
      "github/codeql-action/analyze@v4",
      "javascript-typescript",
      "python",
      "queries: +security-extended,security-and-quality",
      "category: \"/language:${{ matrix.language }}\"",
      "schedule:",
      "workflow_dispatch:",
    ]) {
      if (!text.includes(requiredText)) {
        fail(`${workflow} must include CodeQL security scanning coverage: ${requiredText}`);
      }
    }
  }
  if (isDependencyReviewWorkflow) {
    for (const requiredText of [
      "pull_request:",
      "actions/dependency-review-action@v5",
      "fail-on-severity: moderate",
      "fail-on-scopes: runtime, development, unknown",
      "license-check: true",
      "vulnerability-check: true",
      "comment-summary-in-pr: never",
    ]) {
      if (!text.includes(requiredText)) {
        fail(`${workflow} must include dependency review supply-chain coverage: ${requiredText}`);
      }
    }
  }
}

const dependabot = read(".github/dependabot.yml");
for (const ecosystem of ["npm", "github-actions"]) {
  if (!dependabot.includes(`package-ecosystem: ${ecosystem}`)) {
    fail(`Dependabot must cover ${ecosystem}`);
  }
}
for (const label of ["dependencies", "packaging"]) {
  if (!dependabot.includes(`- ${label}`)) {
    fail(`Dependabot updates must apply the ${label} label`);
  }
  if (!labels.has(label)) {
    fail(`Dependabot references undefined label: ${label}`);
  }
}

const pkg = JSON.parse(read("package.json"));
if (!pkg.engines || pkg.engines.node !== ">=22.0.0") {
  fail("package.json engines.node must require Node >=22.0.0");
}
if (!pkg.engines || pkg.engines.pnpm !== ">=9.15.9 <10.0.0") {
  fail("package.json engines.pnpm must require pnpm >=9.15.9 <10.0.0");
}
if (pkg.packageManager !== "pnpm@9.15.9") {
  fail("package.json packageManager must pin pnpm@9.15.9");
}
if (!pkg.scripts || typeof pkg.scripts !== "object") {
  fail("package.json scripts are required");
}
for (const scriptName of [
  "validate:repo",
  "validate:source-archive",
  "validate:licenses",
  "validate:release",
  "validate:publication",
]) {
  if (!pkg.scripts[scriptName]) {
    fail(`package.json missing required validation script: ${scriptName}`);
  }
}
for (const [name, command] of Object.entries(pkg.scripts)) {
  if (typeof command !== "string" || command.trim() === "") {
    fail(`package.json script ${name} must be a non-empty string`);
  }
  const scriptRefs = [...command.matchAll(/(?:^|[\s;&|()])((?:\.\/)?scripts\/[A-Za-z0-9._/-]+\.sh)(?=$|[\s;&|()])/g)]
    .map((match) => match[1].replace(/^\.\//, ""));
  for (const scriptRef of scriptRefs) {
    if (!fs.existsSync(scriptRef)) {
      fail(`package.json script ${name} references missing script: ${scriptRef}`);
    }
  }
  const directScript = command.trim().match(/^(\.\/)?(scripts\/[A-Za-z0-9._/-]+\.sh)(?:\s|$)/);
  if (directScript) {
    const scriptRef = directScript[2];
    const mode = fs.statSync(scriptRef).mode;
    if ((mode & 0o111) === 0) {
      fail(`package.json script ${name} directly invokes non-executable script: ${scriptRef}`);
    }
  }
}
const license = read("LICENSE");
for (const requiredText of [
  "MIT License",
  "Copyright (c) 2026 DeckSoundpad contributors",
  "Permission is hereby granted, free of charge",
  "THE SOFTWARE IS PROVIDED \"AS IS\"",
]) {
  if (!license.includes(requiredText)) {
    fail(`LICENSE must include standard MIT license text: ${requiredText}`);
  }
}
const changelog = read("CHANGELOG.md");
const escapedVersion = pkg.version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const versionPattern = new RegExp(`^##\\s+\\[?v?${escapedVersion}\\]?(?:\\s+-\\s+\\d{4}-\\d{2}-\\d{2})?\\s*$`, "m");
if (!versionPattern.test(changelog)) {
  fail(`CHANGELOG.md must include a heading for package version ${pkg.version}, preferably with a YYYY-MM-DD date`);
}
if (!/^##\s+Unreleased\s*$/m.test(changelog)) {
  fail("CHANGELOG.md must include an Unreleased section");
}
for (const requiredText of [
  "### Added",
  "### Changed",
  "### Security",
  "Open-source readiness tracking",
  "Release packaging checks",
  "local-only security model",
]) {
  if (!changelog.includes(requiredText)) {
    fail(`CHANGELOG.md must include release evidence text: ${requiredText}`);
  }
}

const gitignore = read(".gitignore");
for (const required of [
  "node_modules/",
  ".pnpm-store/",
  ".tmp-run/",
  ".playwright-mcp/",
  "/dist/",
  "out/",
  "backend/out/",
  "__pycache__/",
  "*.py[cod]",
  "*.log",
  "*.log.*",
  "*.pid",
  ".env",
  ".DS_Store",
  "CLAUDE.md",
  ".pytest_cache/",
  ".mypy_cache/",
  ".ruff_cache/",
  ".coverage",
  "htmlcov/",
  ".venv/",
  "venv/",
]) {
  if (!gitignore.includes(required)) {
    fail(`.gitignore must include: ${required}`);
  }
}

const editorconfig = read(".editorconfig");
for (const required of [
  "root = true",
  "charset = utf-8",
  "end_of_line = lf",
  "insert_final_newline = true",
  "indent_style = space",
  "indent_size = 2",
  "[*.py]",
  "indent_size = 4",
  "[*.md]",
  "trim_trailing_whitespace = false",
]) {
  if (!editorconfig.includes(required)) {
    fail(`.editorconfig must include: ${required}`);
  }
}

const gitattributes = read(".gitattributes");
for (const required of [
  "* text=auto eol=lf",
  "*.zip binary",
  "/out export-ignore",
  "/dist export-ignore",
  "/backend/out export-ignore",
  "/node_modules export-ignore",
  "/.pnpm-store export-ignore",
  "/.tmp-run export-ignore",
  "/.playwright-mcp export-ignore",
  "/.pytest_cache export-ignore",
  "/.mypy_cache export-ignore",
  "/.ruff_cache export-ignore",
  "/.coverage export-ignore",
  "/htmlcov export-ignore",
  "/.venv export-ignore",
  "/venv export-ignore",
  ".env export-ignore",
  "__pycache__ export-ignore",
  "*.py[cod] export-ignore",
  "*.pid export-ignore",
  ".DS_Store export-ignore",
  "CLAUDE.md export-ignore",
  "*.log export-ignore",
  "*.log.* export-ignore",
]) {
  if (!gitattributes.includes(required)) {
    fail(`.gitattributes must include: ${required}`);
  }
}

const markdownFiles = [
  "README.md",
  "CONTRIBUTING.md",
  "SECURITY.md",
  "SUPPORT.md",
  "CODE_OF_CONDUCT.md",
  "CHANGELOG.md",
  ".github/PULL_REQUEST_TEMPLATE.md",
  ...fs.readdirSync("docs")
    .filter((name) => name.endsWith(".md"))
    .map((name) => path.join("docs", name)),
];

for (const file of markdownFiles) {
  const text = read(file);
  const linkPattern = /!?\[[^\]]*\]\(([^)]+)\)/g;
  for (const match of text.matchAll(linkPattern)) {
    let target = match[1].trim();
    if (target.startsWith("<") && target.endsWith(">")) {
      target = target.slice(1, -1);
    }
    target = target.split(/\s+["'][^"']*["']\s*$/)[0];
    if (
      target === "" ||
      target.startsWith("#") ||
      /^[a-z][a-z0-9+.-]*:/i.test(target)
    ) {
      continue;
    }
    const withoutAnchor = target.split("#")[0];
    if (!withoutAnchor) continue;
    const decoded = decodeURIComponent(withoutAnchor);
    const absolute = path.resolve(path.dirname(file), decoded);
    const root = path.resolve(".");
    const relative = path.relative(root, absolute);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
      fail(`${file} links outside the repository: ${target}`);
    }
    if (!fs.existsSync(absolute)) {
      fail(`${file} has a broken local link: ${target}`);
    }
  }
}
NODE

echo "Repository hygiene validation passed."
