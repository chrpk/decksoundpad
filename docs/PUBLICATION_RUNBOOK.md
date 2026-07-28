# Publication runbook

Use this runbook to make the repository public and publish a release. The
short version is: configure GitHub once, validate a clean tagged commit, keep
the external evidence, then upload the exact artifact produced from that tag.

Track remaining blockers in [release readiness](OPEN_SOURCE_READINESS.md).
Detailed branch, tag, and workflow settings live in
[repository settings](REPOSITORY_SETTINGS.md).
The underlying files are `docs/REPOSITORY_SETTINGS.md`,
`docs/DECKBREW_SUBMISSION_CHECKLIST.md`,
`docs/DECKBREW_SUBMISSION_EVIDENCE.md`, and `docs/INSTALLATION.md`.

## 1. Prepare GitHub

Before changing visibility:

1. Run the secret scan and complete real-device validation.
2. Confirm the repository description, topics, issue links, and package metadata.
3. Enable private vulnerability reporting or publish a private security contact.
4. Enable dependency graph, Dependabot alerts, CodeQL, and secret scanning with
   push protection where available.
5. Apply the branch and tag rules from
   [repository settings](REPOSITORY_SETTINGS.md).
6. Run the hosted `CI`, `CodeQL`, `Dependency Review`, and `Secret Scan`
   workflows at least once.

Apply `.github/labels.yml` after publication:

```bash
DRY_RUN=1 corepack pnpm run labels:sync
corepack pnpm run labels:sync
```

The first command is a preview. Blank issues stay disabled so reports use the
structured templates.

## 2. Validate the release candidate

Create a release checklist issue from
`.github/ISSUE_TEMPLATE/release_checklist.yml`. From a clean checkout, using
Node 22 and pnpm 9.15.9, run:

```bash
nvm use
corepack pnpm install --frozen-lockfile
corepack pnpm run check
corepack pnpm run validate:repo
corepack pnpm run validate:deckbrew
corepack pnpm run validate:source-archive
corepack pnpm run validate:licenses
corepack pnpm run scan:python-security
corepack pnpm run scan:secrets
corepack pnpm run package
corepack pnpm run validate:release
```

Record the commit SHA, test/security results, manifest, ZIP filename, checksum,
and relevant hosted workflow URLs in the release issue. The local secret scan
is intentionally narrower than a dedicated full-history scanner, so keep the
hosted full-history result too.

Complete [hardware validation](HARDWARE_VALIDATION.md) on a real Steam Deck and
update [compatibility](COMPATIBILITY.md) before making support claims. Prepare
only redacted media that follows [release assets](RELEASE_ASSETS.md).

## 3. Tag and build

Confirm that:

- `package.json`, `plugin.json`, the Python backend, and `CHANGELOG.md` use the
  same version;
- `package.json` still has `"private": true`;
- the working tree is clean;
- release-note placeholders are gone.

Then create a `vX.Y.Z` tag and run the strict gate:

```bash
DECKSOUNDPAD_REQUIRE_CLEAN_TREE=1 \
DECKSOUNDPAD_REQUIRE_TAG=1 \
corepack pnpm run validate:release
```

Push the tag only after that passes. The `Tagged Release Artifact` workflow
must validate the same commit and attach its versioned ZIP and `.sha256` file
to the matching GitHub Release.

The checksum belongs to the exact uploaded ZIP. Do not replace a hosted ZIP or
checksum with one from a later local rebuild: `RELEASE_MANIFEST.json` contains
its build-specific `generatedAt` evidence.

## 4. Prove publication readiness

`validate:publication` intentionally fails until external work is evidenced.
Provide these values as `1`, a version, or an HTTPS/file evidence path as
appropriate:

```text
DECKSOUNDPAD_REPOSITORY_SETTINGS_APPLIED
DECKSOUNDPAD_LABELS_SYNCED
DECKSOUNDPAD_PRIVATE_VULN_REPORTING_CONFIRMED
DECKSOUNDPAD_SECURITY_CONTACT_EVIDENCE
DECKSOUNDPAD_FULL_HISTORY_SECRET_SCAN_EVIDENCE
DECKSOUNDPAD_HARDWARE_VALIDATION_EVIDENCE
DECKSOUNDPAD_RELEASE_MEDIA_EVIDENCE
DECKSOUNDPAD_RELEASE_ARTIFACT_EVIDENCE
DECKSOUNDPAD_RELEASE_CHECKSUM_EVIDENCE
DECKSOUNDPAD_CI_RUN_EVIDENCE
DECKSOUNDPAD_CODEQL_RUN_EVIDENCE
DECKSOUNDPAD_DEPENDENCY_REVIEW_RUN_EVIDENCE
DECKSOUNDPAD_SECRET_SCAN_RUN_EVIDENCE
DECKSOUNDPAD_TAGGED_ARTIFACT_RUN_EVIDENCE
DECKSOUNDPAD_MIN_STEAMOS_VERSION
DECKSOUNDPAD_MIN_DECKY_LOADER_VERSION
DECKSOUNDPAD_ROOT_FLAG_DECISION
```

Use either private vulnerability reporting or a private security-contact
proof. Then run:

```bash
corepack pnpm run validate:publication
```

## 5. Optional store submission

A GitHub release and a plugin-index submission are separate gates.

For Decky Store or another plugin index, add a public HTTPS PNG to
`plugin.json` and run:

```bash
DECKSOUNDPAD_REQUIRE_DECKY_STORE=1 corepack pnpm run validate:publication
```

For Deckbrew / Decky Plugin Database, keep the
[submission checklist](DECKBREW_SUBMISSION_CHECKLIST.md) and
[evidence form](DECKBREW_SUBMISSION_EVIDENCE.md) current. Provide:

```text
DECKSOUNDPAD_PUBLIC_REPOSITORY_EVIDENCE
DECKSOUNDPAD_LLM_CODE_PROVENANCE_EVIDENCE
DECKSOUNDPAD_DECKBREW_STEAMOS_TEST_EVIDENCE
DECKSOUNDPAD_DECKBREW_DATABASE_PR_EVIDENCE
```

Then run:

```bash
DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1 corepack pnpm run validate:release
DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1 corepack pnpm run validate:publication
```

Static scanning cannot prove maintainer-owned code provenance or SteamOS test
results; link evidence for the exact submitted commit. The database-PR evidence
should point to the pull request that adds this public repository under
`plugins/`.

## 6. Publish and verify

Publish release notes based on [the template](RELEASE_NOTES_TEMPLATE.md) and
link users to [installation and rollback](INSTALLATION.md). Upload only the
strict tagged build's ZIP and checksum.

After publication, verify the README, install/update flow, checksum, ZIP
contents, issue templates, security-reporting route, and downloadable assets as
an anonymous user. Keep the release issue as the audit trail; do not copy its
history back into permanent docs.
