# Publication Runbook

Use this runbook when creating the public GitHub repository and first release.
It turns the remaining open-source readiness blockers into concrete repository
setup actions. Keep `docs/REPOSITORY_SETTINGS.md` open while applying the
GitHub settings so branch protection, security features, and required workflows
match the repository hygiene gates.

## 1. Create The Public Repository

Choose the final owner and repository name. Recommended repository metadata:

- Name: `decksoundpad`
- Description: `Decky Loader soundboard that mixes sounds with the real microphone into a virtual mic.`
- Topics: `decky`, `steam-deck`, `decky-loader`, `soundboard`, `pipewire`,
  `microphone`, `steamos`
- Visibility: public only after the secret scan and hardware validation are
  complete.

After the remote exists:

```bash
git remote add origin git@github.com:<owner>/decksoundpad.git
git remote -v
```

Then update:

- `package.json` repository, bugs, and homepage fields.
- README badges or repository links.
- `SECURITY.md` private reporting text if the final security channel differs.
- `.github/ISSUE_TEMPLATE/config.yml` contact links if the final repository
  uses external support or a dedicated private security intake URL.
- `plugin.json` `publish.image` after a public PNG thumbnail exists.
- release media paths or URLs according to `docs/RELEASE_ASSETS.md`.
- `docs/OPEN_SOURCE_READINESS.md` evidence for the repository URL.

## 2. Enable Security Features

Before accepting public reports:

- Enable private vulnerability reporting in repository settings.
- Enable Dependabot alerts and dependency graph.
- Enable code scanning for CodeQL results if it is not already available for
  the public repository.
- Enable secret scanning and push protection when available for the repository.
- Configure the `GITLEAKS_LICENSE` repository secret if the repository is owned
  by an organization and the Gitleaks action requires it.
- Run the `CodeQL` workflow once and review any initial code scanning alerts.
- Review the first `Dependency Review` workflow result on a dependency-changing
  pull request.
- Run the `Secret Scan` workflow once against full history.

Do not mark the full secret-scan blocker complete until a GitHub/Gitleaks or
equivalent full-history scan has passed.

## 3. Apply Labels

Apply `.github/labels.yml` after publication. If using GitHub CLI:

```bash
DRY_RUN=1 corepack pnpm run labels:sync
corepack pnpm run labels:sync
```

The dry run previews the configured labels. The second command creates missing
labels and updates existing labels to match `.github/labels.yml`.

Required labels:

- `bug`
- `documentation`
- `enhancement`
- `security`
- `audio-routing`
- `steam-deck`
- `external-overlay`
- `sound-library`
- `packaging`
- `dependencies`
- `good-first-issue`

Blank issues are disabled so public reports use the bug, feature, or release
templates that include redaction and diagnostics prompts.

## 4. Protect Main

Configure branch protection or repository rules for `main`:

- Require pull requests before merging.
- Require the `CI` workflow.
- Require the `CodeQL` workflow once the initial scan has passed.
- Require the `Dependency Review` workflow once the first dependency-changing
  pull request has passed.
- Require the `Secret Scan` workflow once configured.
- Block force pushes.
- Require conversation resolution.

## 5. Validate A Release Candidate

Create a release checklist issue from `.github/ISSUE_TEMPLATE/release_checklist.yml`.

Run locally from a clean checkout:

```bash
git status --short
corepack pnpm run validate:repo
corepack pnpm run validate:source-archive
corepack pnpm run validate:licenses
corepack pnpm run validate:release
```

`corepack pnpm run validate:release` includes the local high-confidence secret
scan for tracked files, untracked non-ignored publication files, lockfile URLs,
and git-history patches. Keep the separate full-history GitHub/Gitleaks result
in the release issue because the local scan is intentionally narrower than a
dedicated secret scanner.

After the release commit is tagged, run the strict release gate:

```bash
DECKSOUNDPAD_REQUIRE_CLEAN_TREE=1 DECKSOUNDPAD_REQUIRE_TAG=1 corepack pnpm run validate:release
```

Push the matching `vX.Y.Z` tag only after strict local validation passes. The
`Tagged Release Artifact` workflow then validates the same tagged commit with
the clean-tree and tag gates enabled. It derives the expected artifact version
from `package.json`, uploads only the matching ZIP plus checksum as a workflow
artifact, and attaches the same files to the matching GitHub Release.

For a Decky Store or plugin-index submission, also run:

```bash
DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE=1 corepack pnpm run validate:release
```

For a Deckbrew / Decky Plugin Database submission, also keep
`docs/DECKBREW_SUBMISSION_CHECKLIST.md` and
`docs/DECKBREW_SUBMISSION_EVIDENCE.md` current and run:

```bash
corepack pnpm run validate:deckbrew
DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1 corepack pnpm run validate:release
```

The Deckbrew gate rejects tracked opaque binaries, source maps, minified
review targets, LLM-provider runtime signals, paid-feature/payment signals, and
known keyshop links. It also requires an HTTPS PNG `plugin.json`
`publish.image` and maintainer LLM/code-provenance evidence when
`DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1`.

Attach the output or summarize:

- package version;
- changelog entry for package version;
- dependency, source-import, icon, and license-text validation result;
- source archive policy validation result;
- commit SHA;
- ZIP filename;
- `RELEASE_MANIFEST.json` contents from inside the ZIP;
- SHA-256 checksum;
- ZIP inspection result;
- test result;
- secret scan result;
- CodeQL code scanning result;
- Dependency Review workflow result for dependency or GitHub Actions changes;
- `Tagged Release Artifact` workflow run URL.
- GitHub Release URL containing the ZIP and checksum assets.

If creating a GitHub source archive or exported source tarball, rely on
`.gitattributes` `export-ignore` rules and verify the candidate archive policy
with `corepack pnpm run validate:source-archive`. The archive must not contain
`dist/`, `out/`, dependency folders, caches, logs, `.env`, Python bytecode, or
virtual environment directories.

## 6. Complete Hardware Validation

Fill out `docs/HARDWARE_VALIDATION.md` on real Steam Deck hardware.

Do not publish until the release issue records:

- SteamOS version;
- Decky Loader version;
- audio route result;
- external overlay result;
- root-flag diagnostic result;
- screenshots or demo assets;
- release asset privacy/naming review from `docs/RELEASE_ASSETS.md`;
- minimum supported SteamOS and Decky Loader versions.
- `docs/COMPATIBILITY.md` update for supported version claims.

## 7. Publish The Release

Before publishing:

- Confirm `package.json` and `backend/decksoundpad/__init__.py` versions match.
- Confirm `package.json` still has `"private": true`; do not publish this
  Decky plugin to npm.
- Confirm `CHANGELOG.md` has an entry for the release.
- Confirm `docs/OPEN_SOURCE_READINESS.md` has evidence for all release blockers.
- Confirm the ZIP and `.sha256` files came from the strict tagged-release
  validation command above or the GitHub Release assets published by the
  `Tagged Release Artifact` workflow.
- Treat the checksum as evidence for that exact uploaded ZIP. Do not substitute
  a checksum from a later local rebuild because `RELEASE_MANIFEST.json`
  includes build-specific `generatedAt` evidence.
- Draft release notes from `docs/RELEASE_NOTES_TEMPLATE.md` and remove every
  placeholder.
- Confirm release notes link users to `docs/INSTALLATION.md` for update,
  rollback, uninstall, and recovery guidance.
- Run `corepack pnpm run validate:publication` with the external evidence
  variables below. This command intentionally fails until repository settings,
  hosted workflow results, hardware validation, release media, and the tagged
  artifact are all proven.

Publication readiness variables:

- `DECKSOUNDPAD_REPOSITORY_SETTINGS_APPLIED=1`
- `DECKSOUNDPAD_LABELS_SYNCED=1`
- `DECKSOUNDPAD_PRIVATE_VULN_REPORTING_CONFIRMED=1` or
  `DECKSOUNDPAD_SECURITY_CONTACT_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_FULL_HISTORY_SECRET_SCAN_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_HARDWARE_VALIDATION_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_RELEASE_MEDIA_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_RELEASE_ARTIFACT_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_RELEASE_CHECKSUM_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_CI_RUN_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_CODEQL_RUN_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_DEPENDENCY_REVIEW_RUN_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_SECRET_SCAN_RUN_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_TAGGED_ARTIFACT_RUN_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_MIN_STEAMOS_VERSION=<validated version>`
- `DECKSOUNDPAD_MIN_DECKY_LOADER_VERSION=<validated version>`
- `DECKSOUNDPAD_ROOT_FLAG_DECISION=keep`, `remove`, or `split`

For Decky Store or plugin-index submission, also set
`DECKSOUNDPAD_REQUIRE_DECKY_STORE=1` so `validate:publication` requires an
HTTPS PNG `plugin.json` `publish.image`.

For Deckbrew / Decky Plugin Database submission, set
`DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1` and also provide:

- `DECKSOUNDPAD_PUBLIC_REPOSITORY_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_LLM_CODE_PROVENANCE_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_DECKBREW_STEAMOS_TEST_EVIDENCE=<https URL or file>`
- `DECKSOUNDPAD_DECKBREW_DATABASE_PR_EVIDENCE=<https URL or file>`

`DECKSOUNDPAD_DECKBREW_DATABASE_PR_EVIDENCE` should point to the Decky Plugin
Database pull request or draft pull request showing this public repository as a
submodule under `plugins/`.
`DECKSOUNDPAD_LLM_CODE_PROVENANCE_EVIDENCE` should point to maintainer-owned
evidence for the exact submitted commit, because Deckbrew's LLM/code-provenance
rule cannot be proven by static repository scanning alone.
The same evidence links should be mirrored in
`docs/DECKBREW_SUBMISSION_EVIDENCE.md` or in a linked release issue.

Upload:

- `out/DeckSoundpad-v<version>-full.zip`
- `out/DeckSoundpad-v<version>-full.zip.sha256`

Release notes should include:

- summary of user-facing changes;
- minimum SteamOS and Decky Loader versions tested;
- root-flag rationale outcome;
- known limitations;
- tagged artifact workflow run URL;
- checksum.
