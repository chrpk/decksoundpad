#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required Deckbrew validation command not found: $1" >&2
    exit 1
  fi
}

for command_name in git node; do
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
  return execFileSync("git", args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim();
}

function isTruthy(value) {
  return /^(1|true|yes)$/i.test(value || "");
}

function isUrl(value) {
  return /^https:\/\/[^\s]+$/i.test(value || "");
}

function requireEvidence(name, description) {
  const value = (process.env[name] || "").trim();
  if (!value) {
    fail(`${name} is required: ${description}`);
    return;
  }
  if (isUrl(value)) return;
  if (fs.existsSync(value)) return;
  fail(`${name} must be an HTTPS URL or an existing local evidence file: ${description}`);
}

function listPublishableFiles() {
  const output = git(["ls-files", "--cached", "--others", "--exclude-standard"]);
  if (!output) return [];
  return output
    .split(/\r?\n/)
    .filter((file) => file && fs.existsSync(file) && fs.statSync(file).isFile());
}

function isTextLike(file) {
  return /\.(?:cjs|css|html|js|json|jsx|md|mjs|py|sh|toml|ts|tsx|txt|yml|yaml)$/i.test(file) ||
    /^(README|LICENSE|SECURITY|SUPPORT|CONTRIBUTING|CHANGELOG|CODE_OF_CONDUCT)(?:\.md)?$/i.test(file);
}

if (!fs.existsSync("LICENSE") && !fs.existsSync("LICENSE.MD")) {
  fail("Deckbrew submissions require a LICENSE or LICENSE.MD file");
}

const pkg = readJson("package.json");
const plugin = readJson("plugin.json");
if (pkg.private !== true) {
  fail("package.json private must remain true so the plugin is distributed through Decky/GitHub artifacts, not npm");
}
if (pkg.license !== "MIT") {
  fail("package.json license must match the repository LICENSE");
}
if (!plugin.publish || !Array.isArray(plugin.publish.tags) || !plugin.publish.description) {
  fail("plugin.json publish metadata is required for a Deckbrew submission");
}

const deckbrewSubmissionRequired = isTruthy(process.env.DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION);

if (deckbrewSubmissionRequired || isTruthy(process.env.DECKSOUNDPAD_REQUIRE_DECKY_STORE)) {
  if (!plugin.publish || !/^https:\/\/.+\.png(?:\?.*)?$/i.test(plugin.publish.image || "")) {
    fail("plugin.json publish.image must be an HTTPS PNG URL for Deckbrew/plugin-index submission");
  }
}

if (deckbrewSubmissionRequired) {
  requireEvidence(
    "DECKSOUNDPAD_LLM_CODE_PROVENANCE_EVIDENCE",
    "maintainer evidence that the submitted commit satisfies Deckbrew's LLM/code-provenance rule",
  );
}

const publishableFiles = listPublishableFiles();
const opaqueBinaryPattern = /\.(?:a|bin|bz2|class|dll|dylib|exe|gz|jar|o|rar|so|tar|tgz|wasm|xz|zip|7z)$/i;
const minifiedPattern = /\.min\.(?:css|js)$/i;
const sourceMapPattern = /\.map$/i;
for (const file of publishableFiles) {
  if (opaqueBinaryPattern.test(file)) {
    fail(`Publishable opaque binary/archive file is not Deckbrew-submission ready: ${file}`);
  }
  if (minifiedPattern.test(file)) {
    fail(`Publishable minified source is not allowed for Deckbrew review: ${file}`);
  }
  if (sourceMapPattern.test(file)) {
    fail(`Publishable source map should not be submitted or packaged: ${file}`);
  }
}

const runtimeFiles = publishableFiles.filter((file) =>
  file === "main.py" ||
  file === "plugin.json" ||
  file === "package.json" ||
  file.startsWith("src/") ||
  file.startsWith("backend/decksoundpad/") ||
  file.startsWith("defaults/")
);

const llmPattern = /\b(?:anthropic|chatgpt|gemini|gpt-?[0-9a-z.-]*|large language model|language model|llm|machine learning|neural network|openai)\b/i;
const paymentPattern = /\b(?:donat(?:e|ion)|license key|paid|patreon|payment|paypal|premium|purchase|stripe|subscription|subscribe)\b/i;
for (const file of runtimeFiles) {
  if (!isTextLike(file)) continue;
  const text = read(file);
  if (llmPattern.test(text)) {
    fail(`Runtime file appears to include LLM/AI-provider behavior and needs human review before Deckbrew submission: ${file}`);
  }
  if (paymentPattern.test(text)) {
    fail(`Runtime file appears to include payment, paid-feature, or donation behavior: ${file}`);
  }
}

const keyshopDomains = [
  "cdkeys",
  "eneba",
  "g2a",
  "gamivo",
  "instant-gaming",
  "kinguin",
];
const urlPattern = /https?:\/\/[^\s)>'"]+/gi;
for (const file of publishableFiles) {
  if (!isTextLike(file)) continue;
  const text = read(file);
  for (const match of text.matchAll(urlPattern)) {
    let hostname = "";
    try {
      hostname = new URL(match[0]).hostname.toLowerCase();
    } catch {
      continue;
    }
    if (keyshopDomains.some((domain) => hostname === `${domain}.com` || hostname.endsWith(`.${domain}.com`))) {
      fail(`Repository links to a keyshop domain forbidden by Deckbrew policy: ${file} -> ${hostname}`);
    }
  }
}

const expectedPythonBackendFiles = [
  "main.py",
  "backend/decksoundpad/app.py",
  "backend/decksoundpad/audio_router.py",
  "backend/decksoundpad/audio_player.py",
];
for (const file of expectedPythonBackendFiles) {
  if (!fs.existsSync(file)) {
    fail(`Expected Python backend file is missing: ${file}`);
  }
}

if (failures.length > 0) {
  console.error("Deckbrew submission validation failed:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log("Deckbrew submission validation passed.");
NODE
