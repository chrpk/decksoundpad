#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required publication readiness command not found: $1" >&2
    exit 1
  fi
}

for command_name in git node corepack; do
  require_command "$command_name"
done

node <<'NODE'
const { execFileSync } = require("child_process");
const fs = require("fs");

const failures = [];

function fail(message) {
  failures.push(message);
}

function read(file) {
  return fs.readFileSync(file, "utf8");
}

function readJson(file) {
  return JSON.parse(read(file));
}

function git(args) {
  try {
    return execFileSync("git", args, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

function env(name) {
  return (process.env[name] || "").trim();
}

function isTruthy(value) {
  return /^(1|true|yes)$/i.test(value);
}

function isUrl(value) {
  return /^https:\/\/[^\s]+$/i.test(value);
}

function requireBoolean(name, description) {
  if (!isTruthy(env(name))) {
    fail(`${name}=1 is required: ${description}`);
  }
}

function requireEvidence(name, description) {
  const value = env(name);
  if (!value) {
    fail(`${name} is required: ${description}`);
    return;
  }
  if (isUrl(value)) return;
  if (fs.existsSync(value)) return;
  fail(`${name} must be an HTTPS URL or an existing local evidence file: ${description}`);
}

function requireText(name, description) {
  const value = env(name);
  if (!value || /^(unknown|tbd|todo|n\/a)$/i.test(value)) {
    fail(`${name} is required: ${description}`);
  }
}

const pkg = readJson("package.json");
const plugin = readJson("plugin.json");
const readme = read("README.md");
const security = read("SECURITY.md");
const compatibility = read("docs/COMPATIBILITY.md");

const origin = git(["remote", "get-url", "origin"]);
if (!origin) {
  fail("git remote origin must point at the final public repository");
} else if (/[<>]/.test(origin) || !/github\.com[:/][^/\s]+\/[^/\s]+(?:\.git)?$/i.test(origin)) {
  fail(`git remote origin must be a concrete GitHub repository URL, got: ${origin}`);
}

if (!pkg.repository || typeof pkg.repository !== "object" || !pkg.repository.url) {
  fail("package.json must include the final public repository URL");
}
if (!pkg.bugs || typeof pkg.bugs !== "object" || !pkg.bugs.url) {
  fail("package.json must include the final public issue tracker URL");
}
if (!pkg.homepage) {
  fail("package.json must include the final public homepage URL");
}

if (security.includes("Before the public repository URL is finalized")) {
  fail("SECURITY.md must be updated after the public repository and security intake are finalized");
}

if (!/!\[[^\]]+\]\([^)]+\)/.test(readme) && !/https:\/\/[^\s]*(?:screenshot|demo|release)[^\s]*/i.test(readme)) {
  fail("README.md must include at least one screenshot image or public demo/release media link");
}

for (const phrase of [
  "Minimum supported version not yet established",
  "Requires release-candidate validation",
  "Requires PipeWire/PulseAudio validation on real hardware",
  "Requires Game Mode validation",
]) {
  if (compatibility.includes(phrase)) {
    fail(`docs/COMPATIBILITY.md must replace unresolved compatibility placeholder: ${phrase}`);
  }
}

if (process.env.DECKSOUNDPAD_REQUIRE_DECKY_STORE === "1") {
  const image = plugin.publish && plugin.publish.image;
  if (!image || !/^https:\/\/.+\.png(?:\?.*)?$/i.test(image)) {
    fail("plugin.json publish.image must be an HTTPS PNG URL when DECKSOUNDPAD_REQUIRE_DECKY_STORE=1");
  }
}

requireBoolean(
  "DECKSOUNDPAD_REPOSITORY_SETTINGS_APPLIED",
  "GitHub repository settings match docs/REPOSITORY_SETTINGS.md",
);
requireBoolean(
  "DECKSOUNDPAD_LABELS_SYNCED",
  "labels from .github/labels.yml have been applied to the public repository",
);

if (!isTruthy(env("DECKSOUNDPAD_PRIVATE_VULN_REPORTING_CONFIRMED"))) {
  requireEvidence(
    "DECKSOUNDPAD_SECURITY_CONTACT_EVIDENCE",
    "private vulnerability reporting is enabled or a private security contact is published",
  );
}

requireEvidence(
  "DECKSOUNDPAD_FULL_HISTORY_SECRET_SCAN_EVIDENCE",
  "Gitleaks, GitHub secret scanning, or equivalent full-history secret scan result",
);
requireEvidence(
  "DECKSOUNDPAD_HARDWARE_VALIDATION_EVIDENCE",
  "completed real Steam Deck hardware validation record or release issue",
);
requireEvidence(
  "DECKSOUNDPAD_RELEASE_MEDIA_EVIDENCE",
  "release screenshots, README screenshots, or demo clip evidence",
);
requireEvidence(
  "DECKSOUNDPAD_RELEASE_ARTIFACT_EVIDENCE",
  "published DeckSoundpad-vX.Y.Z-full.zip release artifact",
);
requireEvidence(
  "DECKSOUNDPAD_RELEASE_CHECKSUM_EVIDENCE",
  "published SHA-256 checksum for the exact release ZIP",
);
requireEvidence("DECKSOUNDPAD_CI_RUN_EVIDENCE", "first public CI workflow result");
requireEvidence("DECKSOUNDPAD_CODEQL_RUN_EVIDENCE", "first public CodeQL workflow result");
requireEvidence(
  "DECKSOUNDPAD_DEPENDENCY_REVIEW_RUN_EVIDENCE",
  "first public Dependency Review workflow result for a dependency-changing pull request",
);
requireEvidence(
  "DECKSOUNDPAD_SECRET_SCAN_RUN_EVIDENCE",
  "first public full-history Secret Scan workflow result",
);
requireEvidence(
  "DECKSOUNDPAD_TAGGED_ARTIFACT_RUN_EVIDENCE",
  "first public Tagged Release Artifact workflow result",
);

requireText("DECKSOUNDPAD_MIN_STEAMOS_VERSION", "minimum supported SteamOS version from hardware validation");
requireText(
  "DECKSOUNDPAD_MIN_DECKY_LOADER_VERSION",
  "minimum supported Decky Loader version from hardware validation",
);

const rootDecision = env("DECKSOUNDPAD_ROOT_FLAG_DECISION");
if (!/^(keep|remove|split)$/i.test(rootDecision)) {
  fail("DECKSOUNDPAD_ROOT_FLAG_DECISION must be one of: keep, remove, split");
} else if (/^keep$/i.test(rootDecision) && (!Array.isArray(plugin.flags) || !plugin.flags.includes("root"))) {
  fail("DECKSOUNDPAD_ROOT_FLAG_DECISION=keep requires plugin.json to retain flags: [\"root\"]");
} else if (/^remove$/i.test(rootDecision) && Array.isArray(plugin.flags) && plugin.flags.includes("root")) {
  fail("DECKSOUNDPAD_ROOT_FLAG_DECISION=remove requires plugin.json to remove the root flag");
}

if (failures.length > 0) {
  console.error("Publication readiness validation failed:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log("Publication readiness evidence is present. Running local release validation next.");
NODE

if [[ "${DECKSOUNDPAD_SKIP_LOCAL_PUBLICATION_GATES:-0}" != "1" ]]; then
  corepack pnpm run validate:release
else
  echo "Skipped local release validation because DECKSOUNDPAD_SKIP_LOCAL_PUBLICATION_GATES=1."
fi

echo "Publication readiness validation passed."
