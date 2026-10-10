#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required source archive validation command not found: $1" >&2
    exit 1
  fi
}

for command_name in git node; do
  require_command "$command_name"
done

node <<'NODE'
const { execFileSync } = require("child_process");

function fail(message) {
  console.error(message);
  process.exit(1);
}

function gitOutput(args) {
  return execFileSync("git", args, {
    encoding: "buffer",
    stdio: ["ignore", "pipe", "pipe"],
  });
}

const files = gitOutput(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
  .toString("utf8")
  .split("\0")
  .filter(Boolean)
  .sort((left, right) => left.localeCompare(right));

if (files.length === 0) {
  fail("No tracked or publishable untracked files were found for source archive validation");
}

function exportIgnored(file) {
  const parts = gitOutput(["check-attr", "-z", "export-ignore", "--", file])
    .toString("utf8")
    .split("\0");
  return parts[2] === "set";
}

const included = [];
const ignored = [];
for (const file of files) {
  if (exportIgnored(file)) {
    ignored.push(file);
  } else {
    included.push(file);
  }
}

const includedSet = new Set(included);
const requiredIncluded = [
  ".editorconfig",
  ".gitattributes",
  ".github/PULL_REQUEST_TEMPLATE.md",
  ".github/ISSUE_TEMPLATE/bug_report.yml",
  ".github/workflows/ci.yml",
  ".github/workflows/codeql.yml",
  ".github/workflows/dependency-review.yml",
  ".github/workflows/release.yml",
  ".github/workflows/secret-scan.yml",
  ".gitignore",
  ".gitleaks.toml",
  ".nvmrc",
  "CHANGELOG.md",
  "CODE_OF_CONDUCT.md",
  "CONTRIBUTING.md",
  "LICENSE",
  "README.md",
  "SECURITY.md",
  "SUPPORT.md",
  "backend/decksoundpad/__init__.py",
  "backend/decksoundpad/app.py",
  "backend/tests/test_app.py",
  "defaults/config.default.json",
  "docs/ARCHITECTURE.md",
  "docs/BRIDGE_API.md",
  "docs/INSTALLATION.md",
  "docs/THIRD_PARTY_LICENSES.md",
  "docs/THIRD_PARTY_NOTICES.md",
  "main.py",
  "package.json",
  "plugin.json",
  "pnpm-lock.yaml",
  "rollup.config.js",
  "scripts/package_plugin.sh",
  "scripts/validate_deckbrew_submission.sh",
  "scripts/validate_release.sh",
  "scripts/validate_repo_hygiene.sh",
  "scripts/validate_publication_readiness.sh",
  "scripts/validate_source_archive.sh",
  "src/buildInfo.ts",
  "src/index.tsx",
  "tsconfig.json",
];

for (const file of requiredIncluded) {
  if (!files.includes(file)) {
    fail(`Required source archive file is missing from tracked/untracked publishable files: ${file}`);
  }
  if (!includedSet.has(file)) {
    fail(`Required source archive file is unexpectedly export-ignored: ${file}`);
  }
}

const forbiddenIncludedPatterns = [
  {
    label: "dependency folders",
    pattern: /(^|\/)(node_modules|\.pnpm-store)(\/|$)/,
  },
  {
    label: "generated output",
    pattern: /(^|\/)(dist|out|backend\/out|htmlcov)(\/|$)/,
  },
  {
    label: "local caches",
    pattern: /(^|\/)(\.tmp-run|\.playwright-mcp|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.coverage)(\/|$)/,
  },
  {
    label: "local virtual environments",
    pattern: /(^|\/)(\.venv|venv)(\/|$)/,
  },
  {
    label: "legacy generated Decky entrypoints",
    pattern: /(^|\/)(cli|decky_plugin\.py)(\/|$)/,
  },
  {
    label: "private environment files",
    pattern: /(^|\/)\.env$/,
  },
  {
    label: "Python bytecode",
    pattern: /\.py[cod]$/,
  },
  {
    label: "logs and local process files",
    pattern: /(^|\/)([^/]+\.log(?:\..*)?|[^/]+\.pid)$/,
  },
  {
    label: "macOS metadata",
    pattern: /(^|\/)\.DS_Store$/,
  },
];

const forbiddenIncluded = [];
for (const file of included) {
  for (const { label, pattern } of forbiddenIncludedPatterns) {
    if (pattern.test(file)) {
      forbiddenIncluded.push(`${file} (${label})`);
      break;
    }
  }
}

if (forbiddenIncluded.length > 0) {
  fail(
    "Source archive policy would include forbidden local/generated files:\n" +
      forbiddenIncluded.map((file) => `- ${file}`).join("\n"),
  );
}

console.log(
  `Source archive policy validation passed for ${included.length} included paths ` +
    `and ${ignored.length} export-ignored paths.`,
);
NODE
