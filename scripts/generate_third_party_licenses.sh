#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUTPUT_PATH="${1:-docs/THIRD_PARTY_LICENSES.md}"

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
        packages.push({
          name: entry.name,
          version,
          license,
          homepage: entry.homepage || "",
          paths: Array.isArray(entry.paths) ? entry.paths : [],
        });
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

function licenseFilesForPackage(pkg) {
  const files = [];
  for (const packagePath of pkg.paths) {
    if (!fs.existsSync(packagePath)) continue;
    for (const entry of fs.readdirSync(packagePath, { withFileTypes: true })) {
      if (!entry.isFile()) continue;
      if (/^(licen[cs]e|copying|notice)(\..*)?$/i.test(entry.name)) {
        files.push(path.join(packagePath, entry.name));
      }
    }
  }
  return [...new Set(files)].sort((left, right) => left.localeCompare(right));
}

const prodPackages = flattenLicenses(readLicenses(["--prod", "--json"]));
const allPackages = flattenLicenses(readLicenses(["--json"]));
const packagesByName = new Map();
for (const pkg of allPackages) {
  if (!packagesByName.has(pkg.name)) packagesByName.set(pkg.name, []);
  packagesByName.get(pkg.name).push(pkg);
}

const selected = new Map();
for (const pkg of prodPackages) {
  selected.set(`${pkg.name}@${pkg.version}`, pkg);
}
for (const name of collectImportedPackageNames()) {
  const importedPackages = packagesByName.get(name) || [];
  if (importedPackages.length === 0) {
    fail(`Unable to find license metadata for source-imported package: ${name}`);
  }
  for (const pkg of importedPackages) {
    selected.set(`${pkg.name}@${pkg.version}`, pkg);
  }
}

const packages = [...selected.values()].sort((left, right) => (
  left.name.localeCompare(right.name) || left.version.localeCompare(right.version)
));

let output = "";
output += "# Third-Party License Texts\n\n";
output += "This file is generated from installed package license files for ";
output += "production dependencies and packages directly imported from `src/`.\n";
output += "Regenerate it with `corepack pnpm run licenses:generate` after dependency changes.\n\n";

for (const pkg of packages) {
  const files = licenseFilesForPackage(pkg);
  if (files.length === 0) {
    fail(`No license or notice file found for ${pkg.name}@${pkg.version}`);
  }
  output += `## ${pkg.name} ${pkg.version}\n\n`;
  output += `License: ${pkg.license}\n`;
  if (pkg.homepage) output += `Homepage: ${pkg.homepage}\n`;
  output += "\n";
  for (const file of files) {
    output += `### ${path.basename(file)}\n\n`;
    output += "```text\n";
    output += fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n").trimEnd();
    output += "\n```\n\n";
  }
}

if (outputPath === "-") {
  process.stdout.write(output);
} else {
  fs.writeFileSync(outputPath, output);
}
NODE
