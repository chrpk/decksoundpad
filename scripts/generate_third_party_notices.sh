#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUTPUT_PATH="${1:-docs/THIRD_PARTY_NOTICES.md}"

node - "$OUTPUT_PATH" <<'NODE'
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const outputPath = process.argv[2];

function fail(message) {
  console.error(message);
  process.exit(1);
}

function readLicenses(args) {
  try {
    return JSON.parse(execFileSync("corepack", ["pnpm", "licenses", "list", ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }));
  } catch (error) {
    fail(`Unable to read dependency licenses. Run corepack pnpm install first. ${error.message}`);
  }
}

function flattenLicenses(licenses) {
  const packages = [];
  for (const [license, entries] of Object.entries(licenses)) {
    for (const entry of entries) {
      const versions = Array.isArray(entry.versions) ? entry.versions : [];
      for (const version of versions) {
        packages.push({ name: entry.name, version, license });
      }
    }
  }
  return packages;
}

function packageNameFromSpecifier(specifier) {
  if (specifier.startsWith(".") || specifier.startsWith("/") || specifier.startsWith("node:")) {
    return null;
  }
  const parts = specifier.split("/");
  return specifier.startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0];
}

function collectSourceFiles(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(absolute));
    } else if (/\.[cm]?[jt]sx?$/.test(entry.name)) {
      files.push(absolute);
    }
  }
  return files;
}

function collectImportedPackageNames() {
  const imported = new Set();
  const importPattern = /\bimport\s+(?:type\s+)?(?:[^"'()]+?\s+from\s+)?["']([^"']+)["']|\bexport\s+(?:type\s+)?(?:[^"']+?\s+from\s+)?["']([^"']+)["']|\bimport\(\s*["']([^"']+)["']\s*\)/g;
  for (const file of collectSourceFiles("src")) {
    const text = fs.readFileSync(file, "utf8");
    for (const match of text.matchAll(importPattern)) {
      const specifier = match[1] || match[2] || match[3];
      const packageName = packageNameFromSpecifier(specifier);
      if (packageName) imported.add(packageName);
    }
  }
  return imported;
}

function collectReactIconsFaImports() {
  const icons = new Set();
  const importPattern = /\bimport\s*\{([^}]+)\}\s*from\s*["']react-icons\/fa["']/g;
  for (const file of collectSourceFiles("src")) {
    const text = fs.readFileSync(file, "utf8");
    for (const match of text.matchAll(importPattern)) {
      for (const rawImport of match[1].split(",")) {
        const iconName = rawImport.trim().split(/\s+as\s+/)[0].trim();
        if (iconName) icons.add(iconName);
      }
    }
  }
  return icons;
}

function packageMetadata(name) {
  try {
    return require(`${name}/package.json`);
  } catch (error) {
    fail(`Unable to read package metadata for ${name}: ${error.message}`);
  }
}

function normalizeSourceUrl(url) {
  return String(url || "")
    .replace(/^git\+/, "")
    .replace(/^git:\/\/github\.com\//, "https://github.com/")
    .replace(/^ssh:\/\/git@github\.com\//, "https://github.com/")
    .replace(/^git@github\.com:/, "https://github.com/")
    .replace(/\.git$/, "")
    .replace(/#readme$/, "");
}

function upstreamSourceUrlForPackage(name) {
  const metadata = packageMetadata(name);
  const repository = metadata.repository;
  let repositoryUrl = "";
  if (typeof repository === "string") {
    repositoryUrl = repository;
  } else if (repository && typeof repository.url === "string") {
    repositoryUrl = repository.url;
  }
  const sourceUrl = normalizeSourceUrl(repositoryUrl || metadata.homepage);
  if (!/^https:\/\/.+/.test(sourceUrl)) {
    fail(`Package ${name} must expose an HTTPS upstream source URL for LGPL source availability review`);
  }
  return sourceUrl;
}

function compareStrings(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function byNameThenVersion(left, right) {
  return compareStrings(left.name, right.name) || compareStrings(left.version, right.version);
}

const prodPackages = flattenLicenses(readLicenses(["--prod", "--json"])).sort(byNameThenVersion);
const allPackages = flattenLicenses(readLicenses(["--json"]));
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
const devDependencyNames = Object.keys(pkg.devDependencies || {}).sort();
const importedPackageNames = [...collectImportedPackageNames()].sort();
const fontAwesomeIcons = [...collectReactIconsFaImports()].sort();
const licenseFamilies = [...new Set(Object.keys(readLicenses(["--json"])))].sort();

const packagesByName = new Map();
for (const candidate of allPackages) {
  if (!packagesByName.has(candidate.name)) packagesByName.set(candidate.name, []);
  packagesByName.get(candidate.name).push(candidate);
}

const devPackages = [];
for (const name of devDependencyNames) {
  const versions = (packagesByName.get(name) || []).slice().sort(byNameThenVersion);
  devPackages.push(...versions);
}

const sourceAvailability = new Map();
function addSourceAvailability(packageEntry, scope) {
  if (!/^LGPL/i.test(packageEntry.license)) return;
  const key = `${packageEntry.name}@${packageEntry.version}@${packageEntry.license}`;
  if (!sourceAvailability.has(key)) {
    sourceAvailability.set(key, { pkg: packageEntry, scopes: [] });
  }
  const entry = sourceAvailability.get(key);
  if (!entry.scopes.includes(scope)) entry.scopes.push(scope);
}

for (const entry of prodPackages) addSourceAvailability(entry, "Production dependency");
for (const name of importedPackageNames) {
  for (const entry of packagesByName.get(name) || []) {
    addSourceAvailability(entry, "Frontend source import");
  }
}
const sourceRows = [...sourceAvailability.values()].sort((left, right) => byNameThenVersion(left.pkg, right.pkg));

let output = "";
output += "# Third-Party Notices\n\n";
output += "This document summarizes the JavaScript dependency license review for the\n";
output += "current public-release baseline. It is generated from local package metadata\n";
output += "with `corepack pnpm licenses list` and a review of `src/` imports. Regenerate\n";
output += "it with `corepack pnpm run notices:generate` after dependency or import\n";
output += "changes.\n\n";
output += "DeckSoundpad's own source code is licensed under MIT. The dependency summary\n";
output += "below is provided for release review. License text for production dependencies\n";
output += "and packages directly imported from `src/` is bundled in\n";
output += "`docs/THIRD_PARTY_LICENSES.md`.\n\n";

output += "## Production Dependencies\n\n";
output += "| Package | Version | License |\n";
output += "| --- | ---: | --- |\n";
for (const entry of prodPackages) {
  output += `| \`${entry.name}\` | ${entry.version} | ${entry.license} |\n`;
}
output += "\n";

output += "## LGPL Source Availability\n\n";
output += "DeckSoundpad distributes Decky LGPL packages only through npm-installed package\n";
output += "contents. No local third-party source modifications are distributed by this\n";
output += "repository. The upstream source locations for LGPL packages used by production\n";
output += "dependencies or imported frontend packages are:\n\n";
output += "| Package | Version | License | Scope | Upstream source |\n";
output += "| --- | ---: | --- | --- | --- |\n";
for (const { pkg: packageEntry, scopes } of sourceRows) {
  const sourceUrl = upstreamSourceUrlForPackage(packageEntry.name);
  output += `| \`${packageEntry.name}\` | ${packageEntry.version} | ${packageEntry.license} | ${scopes.join("; ")} | ${sourceUrl} |\n`;
}
output += "\n";

output += "## Icon Assets\n\n";
output += "DeckSoundpad imports Font Awesome icons through `react-icons/fa`:\n\n";
for (const iconName of fontAwesomeIcons) {
  output += `- \`${iconName}\`\n`;
}
output += "\n";
output += "The `react-icons` package license text bundled in\n";
output += "`docs/THIRD_PARTY_LICENSES.md` lists Font Awesome 5 and Font Awesome 6 under\n";
output += "CC BY 4.0. Keep this attribution section current if icon imports change.\n\n";

output += "## Direct Development Dependencies\n\n";
output += "The table includes every resolved version associated with a direct development\n";
output += "dependency name. A build plugin can therefore contribute an additional version\n";
output += "of a package that is also declared directly, as `@decky/rollup` does for\n";
output += "TypeScript.\n\n";
output += "| Package | Version | License |\n";
output += "| --- | ---: | --- |\n";
for (const entry of devPackages) {
  output += `| \`${entry.name}\` | ${entry.version} | ${entry.license} |\n`;
}
output += "\n";

output += "## Transitive License Families Observed\n\n";
output += "`corepack pnpm licenses list` reported these license families across transitive\n";
output += "dependencies:\n\n";
for (const family of licenseFamilies) {
  output += `- \`${family}\`\n`;
}
output += "\n";
output += "Before each public release, regenerate and verify these notices:\n\n";
output += "```bash\n";
output += "corepack pnpm run notices:generate\n";
output += "corepack pnpm run validate:licenses\n";
output += "```\n\n";
output += "The validator checks production packages, packages directly imported from\n";
output += "`src/`, direct development dependencies, and the transitive license-family list.\n";
output += "It also verifies source-availability rows for LGPL packages used by production\n";
output += "dependencies or imported frontend packages. If this file is stale, run\n";
output += "`corepack pnpm run notices:generate` and review whether the ZIP distribution\n";
output += "needs additional notices.\n";

if (outputPath === "-") {
  process.stdout.write(output);
} else {
  fs.writeFileSync(outputPath, output);
}
NODE
