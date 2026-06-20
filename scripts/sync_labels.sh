#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL_FILE="$ROOT_DIR/.github/labels.yml"
DRY_RUN="${DRY_RUN:-0}"

if [[ ! -f "$LABEL_FILE" ]]; then
  echo "Missing label file: $LABEL_FILE" >&2
  exit 1
fi

if [[ "$DRY_RUN" != "1" ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI is required. Install gh or run with DRY_RUN=1 to preview." >&2
    exit 1
  fi
  gh auth status >/dev/null
fi

node - "$LABEL_FILE" <<'NODE' | while IFS=$'\t' read -r name color description; do
const fs = require("fs");
const path = process.argv[2];
const text = fs.readFileSync(path, "utf8");
const labels = [];
let current = null;

function finish() {
  if (!current) return;
  for (const key of ["name", "color", "description"]) {
    if (!current[key]) {
      console.error(`Label entry is missing ${key}: ${JSON.stringify(current)}`);
      process.exit(1);
    }
  }
  labels.push(current);
  current = null;
}

for (const line of text.split(/\r?\n/)) {
  if (!line.trim()) continue;
  const start = line.match(/^- name:\s*(.+)$/);
  if (start) {
    finish();
    current = { name: start[1].trim() };
    continue;
  }
  const field = line.match(/^\s{2}(color|description):\s*(.+)$/);
  if (field && current) {
    current[field[1]] = field[2].trim();
    continue;
  }
  console.error(`Unsupported labels.yml line: ${line}`);
  process.exit(1);
}
finish();

for (const label of labels) {
  process.stdout.write(`${label.name}\t${label.color}\t${label.description}\n`);
}
NODE
  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'Would sync label: %s (%s) - %s\n' "$name" "$color" "$description"
    continue
  fi

  if gh label view "$name" >/dev/null 2>&1; then
    gh label edit "$name" --color "$color" --description "$description"
  else
    gh label create "$name" --color "$color" --description "$description"
  fi
done
