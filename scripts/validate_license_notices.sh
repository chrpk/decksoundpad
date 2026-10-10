#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

node <<'NODE'
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

function fail(message) {
  console.error(message);
  process.exit(1);
}

const noticePath = "docs/THIRD_PARTY_NOTICES.md";
const notice = fs.readFileSync(noticePath, "utf8");

function readLicenses(args) {
  try {
    return execFileSync("corepack", ["pnpm", "licenses", "list", ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    fail(`Unable to read dependency licenses. Run corepack pnpm install first. ${error.message}`);
  }
}

function parseLicenses(output) {
  try {
    return JSON.parse(output);
  } catch (error) {
    fail(`Unable to parse pnpm license JSON: ${error.message}`);
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

function requireNoticeRows(packages, context) {
  if (packages.length === 0) {
    fail(`No dependency licenses were reported for ${context}`);
  }
  for (const pkg of packages) {
    const expected = `| \`${pkg.name}\` | ${pkg.version} | ${pkg.license} |`;
    if (!notice.includes(expected)) {
      fail(`${noticePath} is missing ${context} notice row: ${expected}`);
    }
  }
}

function sectionRows(sectionTitle) {
  const rows = [];
  for (const line of sectionText(sectionTitle).split(/\r?\n/)) {
    const match = line.match(/^\| `([^`]+)` \| ([^|]+) \| ([^|]+) \|$/);
    if (!match) continue;
    rows.push({
      name: match[1].trim(),
      version: match[2].trim(),
      license: match[3].trim(),
      line,
    });
  }
  return rows;
}

function sectionText(sectionTitle) {
  const sectionStart = notice.indexOf(`## ${sectionTitle}`);
  if (sectionStart === -1) {
    fail(`${noticePath} is missing section: ${sectionTitle}`);
  }
  const nextSection = notice.indexOf("\n## ", sectionStart + 1);
  return nextSection === -1 ? notice.slice(sectionStart) : notice.slice(sectionStart, nextSection);
}

function sectionBacktickBullets(sectionTitle) {
  const values = [];
  for (const line of sectionText(sectionTitle).split(/\r?\n/)) {
    const match = line.match(/^- `([^`]+)`$/);
    if (match) values.push(match[1]);
  }
  return values;
}

function sectionSourceAvailabilityRows() {
  const rows = [];
  for (const line of sectionText("LGPL Source Availability").split(/\r?\n/)) {
    const match = line.match(/^\| `([^`]+)` \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (https?:\/\/[^| ]+) \|$/);
    if (!match) continue;
    rows.push({
      name: match[1].trim(),
      version: match[2].trim(),
      license: match[3].trim(),
      scope: match[4].trim(),
      source: match[5].trim(),
      line,
    });
  }
  return rows;
}

function requireNoticeForPackageName(name, context) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rowPattern = new RegExp(`^\\| \`${escaped}\` \\| [^|]+ \\| [^|]+ \\|$`, "m");
  if (!rowPattern.test(notice)) {
    fail(`${noticePath} is missing ${context} notice row for package: ${name}`);
  }
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

const prodLicenses = parseLicenses(readLicenses(["--prod", "--json"]));
const allLicenses = parseLicenses(readLicenses(["--json"]));
const prodPackages = flattenLicenses(prodLicenses);
const allPackages = flattenLicenses(allLicenses);
const importedPackageNames = collectImportedPackageNames();

requireNoticeRows(prodPackages, "production dependency");
const expectedProductionRows = new Set(prodPackages.map((pkg) => (
  `| \`${pkg.name}\` | ${pkg.version} | ${pkg.license} |`
)));
for (const row of sectionRows("Production Dependencies")) {
  if (!expectedProductionRows.has(row.line)) {
    fail(`${noticePath} has stale or unexpected production dependency notice row: ${row.line}`);
  }
}

const expectedLicenseFamilies = new Set(Object.keys(allLicenses));
const noticeLicenseFamilies = new Set(sectionBacktickBullets("Transitive License Families Observed"));
for (const family of expectedLicenseFamilies) {
  if (!noticeLicenseFamilies.has(family)) {
    fail(`${noticePath} is missing transitive license family: ${family}`);
  }
}
for (const family of noticeLicenseFamilies) {
  if (!expectedLicenseFamilies.has(family)) {
    fail(`${noticePath} has stale or unexpected transitive license family: ${family}`);
  }
}

const packagesByName = new Map();
for (const pkg of allPackages) {
  if (!packagesByName.has(pkg.name)) packagesByName.set(pkg.name, []);
  packagesByName.get(pkg.name).push(pkg);
}

const sourceAvailabilityByKey = new Map();
function addSourceAvailabilityPackage(pkg, scope) {
  if (!/^LGPL/i.test(pkg.license)) return;
  const key = `${pkg.name}@${pkg.version}@${pkg.license}`;
  if (!sourceAvailabilityByKey.has(key)) {
    sourceAvailabilityByKey.set(key, { pkg, scopes: [] });
  }
  const entry = sourceAvailabilityByKey.get(key);
  if (!entry.scopes.includes(scope)) entry.scopes.push(scope);
}

for (const pkg of prodPackages) {
  addSourceAvailabilityPackage(pkg, "Production dependency");
}

for (const name of importedPackageNames) {
  const importedPackages = packagesByName.get(name) || [];
  requireNoticeRows(importedPackages, `source-imported dependency ${name}`);
  for (const pkg of importedPackages) {
    addSourceAvailabilityPackage(pkg, "Frontend source import");
  }
}

if (sourceAvailabilityByKey.size > 0) {
  for (const requiredText of [
    "## LGPL Source Availability",
    "No local third-party source modifications",
    "production",
    "imported frontend packages",
  ]) {
    if (!notice.includes(requiredText)) {
      fail(`${noticePath} must include LGPL source availability text: ${requiredText}`);
    }
  }
}

const expectedSourceAvailabilityRows = new Set();
for (const { pkg, scopes } of sourceAvailabilityByKey.values()) {
  const sourceUrl = upstreamSourceUrlForPackage(pkg.name);
  expectedSourceAvailabilityRows.add(
    `| \`${pkg.name}\` | ${pkg.version} | ${pkg.license} | ${scopes.join("; ")} | ${sourceUrl} |`,
  );
}
for (const expected of expectedSourceAvailabilityRows) {
  if (!notice.includes(expected)) {
    fail(`${noticePath} is missing LGPL source availability row: ${expected}`);
  }
}
for (const row of sectionSourceAvailabilityRows()) {
  if (!expectedSourceAvailabilityRows.has(row.line)) {
    fail(`${noticePath} has stale or unexpected LGPL source availability row: ${row.line}`);
  }
}

const fontAwesomeIcons = collectReactIconsFaImports();
if (fontAwesomeIcons.size > 0) {
  for (const requiredText of ["## Icon Assets", "react-icons/fa", "Font Awesome", "CC BY 4.0"]) {
    if (!notice.includes(requiredText)) {
      fail(`${noticePath} must include Font Awesome icon attribution text: ${requiredText}`);
    }
  }
  for (const iconName of fontAwesomeIcons) {
    if (!notice.includes(`\`${iconName}\``)) {
      fail(`${noticePath} must list imported Font Awesome icon: ${iconName}`);
    }
  }
}

const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
const directDevDependencyNames = new Set(Object.keys(pkg.devDependencies || {}));
const expectedDirectDevRows = new Set();
for (const name of Object.keys(pkg.devDependencies || {})) {
  const devPackages = packagesByName.get(name) || [];
  if (devPackages.length > 0) {
    requireNoticeRows(devPackages, `direct development dependency ${name}`);
    for (const devPackage of devPackages) {
      expectedDirectDevRows.add(`| \`${devPackage.name}\` | ${devPackage.version} | ${devPackage.license} |`);
    }
  } else {
    requireNoticeForPackageName(name, `platform-specific direct development dependency ${name}`);
  }
}
for (const row of sectionRows("Direct Development Dependencies")) {
  if (!directDevDependencyNames.has(row.name)) {
    fail(`${noticePath} has stale or unexpected direct development dependency notice row: ${row.line}`);
  }
  if (expectedDirectDevRows.size > 0 && packagesByName.has(row.name) && !expectedDirectDevRows.has(row.line)) {
    fail(`${noticePath} has stale or unexpected direct development dependency version/license row: ${row.line}`);
  }
}

const thirdPartyLicensesPath = "docs/THIRD_PARTY_LICENSES.md";
if (!fs.existsSync(thirdPartyLicensesPath)) {
  fail(`${thirdPartyLicensesPath} is missing. Run corepack pnpm run licenses:generate.`);
}
let expectedLicenseTexts;
try {
  expectedLicenseTexts = execFileSync("bash", ["scripts/generate_third_party_licenses.sh", "-"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
} catch (error) {
  fail(`Unable to generate expected third-party license text bundle: ${error.message}`);
}
const actualLicenseTexts = fs.readFileSync(thirdPartyLicensesPath, "utf8");
if (actualLicenseTexts !== expectedLicenseTexts) {
  fail(`${thirdPartyLicensesPath} is stale. Run corepack pnpm run licenses:generate.`);
}

const thirdPartyNoticesPath = "docs/THIRD_PARTY_NOTICES.md";
if (!fs.existsSync(thirdPartyNoticesPath)) {
  fail(`${thirdPartyNoticesPath} is missing. Run corepack pnpm run notices:generate.`);
}
let expectedNoticeTexts;
try {
  expectedNoticeTexts = execFileSync("bash", ["scripts/generate_third_party_notices.sh", "-"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
} catch (error) {
  fail(`Unable to generate expected third-party notices document: ${error.message}`);
}
const actualNoticeTexts = fs.readFileSync(thirdPartyNoticesPath, "utf8");
if (actualNoticeTexts !== expectedNoticeTexts) {
  fail(`${thirdPartyNoticesPath} is stale. Run corepack pnpm run notices:generate.`);
}

console.log(
  `License notice validation passed for ${prodPackages.length} production package versions, ` +
    `${importedPackageNames.size} source-imported packages, ` +
    `${sourceAvailabilityByKey.size} LGPL source-availability rows, and ` +
    `${Object.keys(pkg.devDependencies || {}).length} direct development dependencies.`,
);
NODE
