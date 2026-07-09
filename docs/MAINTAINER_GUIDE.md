# Maintainer Guide

This guide defines how to run the public repository after launch. It is scoped
to repository operations; release readiness remains tracked in
`docs/OPEN_SOURCE_READINESS.md`.

## Triage Principles

- Keep security-sensitive details out of public issues.
- Ask for DeckSoundpad version or commit, installation source, Steam Deck
  model, SteamOS version, Decky Loader version, and redacted logs before
  debugging hardware-specific reports.
- Prefer reproducible reports over broad compatibility claims.
- Close issues that require private sound files, voice recordings, credentials,
  or unredacted logs unless the reporter can provide safe reproduction data.
- Do not promise support for unvalidated SteamOS, Decky Loader, or PipeWire
  versions.

## Label Use

- `bug`: confirmed or plausibly reproducible defect.
- `documentation`: docs, release notes, screenshots, or validation records.
- `enhancement`: new feature or behavior change.
- `security`: hardening work or private-report follow-up without exploit detail.
- `audio-routing`: PipeWire, PulseAudio, virtual mic, or passthrough behavior.
- `steam-deck`: SteamOS, Decky Loader, Game Mode, or hardware validation.
- `external-overlay`: overlay process, socket, input capture, or hotkeys.
- `sound-library`: scanning, local paths, formats, categories, or metadata.
- `packaging`: build, ZIP, checksum, CI, or release artifact issues.
- `dependencies`: dependency updates, lockfile changes, or dependency policy.
- `good-first-issue`: small, low-risk, well-described contribution.

## Issue Flow

1. Confirm the issue is not security-sensitive.
2. Apply area labels from `.github/labels.yml`.
3. Ask for missing environment details using the issue-template fields.
4. Reproduce in simulation mode when possible.
5. Require real Steam Deck evidence before changing hardware-sensitive behavior.
6. Link fixes to tests, release checklist issues, or hardware validation notes.

## Pull Request Review

Require:

- `corepack pnpm run check`;
- `corepack pnpm run validate:repo`;
- `corepack pnpm run validate:source-archive`;
- `corepack pnpm run validate:licenses` when dependencies change;
- `corepack pnpm run scan:python-security` for privileged Python changes;
- `corepack pnpm run validate:release` for packaging or release-flow changes;
- Steam Deck validation notes for audio routing, overlay, input, or root-flag
  changes.

Review especially carefully when a change touches:

- module boundaries documented in `docs/ARCHITECTURE.md`;
- subprocess command construction;
- symlink and path handling;
- logs mirrored under `~/Public/DeckSoundpad/logs/`;
- input devices under `/dev/input` or `/dev/hidraw*`;
- PipeWire/PulseAudio module loading or cleanup;
- release packaging scripts and GitHub workflows.

## Release Promotion

A release candidate can become a public release only after:

- every blocker in `docs/OPEN_SOURCE_READINESS.md` has evidence;
- the release checklist issue is complete;
- `corepack pnpm run validate:publication` passes with repository, workflow,
  hardware, media, and artifact evidence variables supplied;
- strict tagged validation passes:
  `DECKSOUNDPAD_REQUIRE_CLEAN_TREE=1 DECKSOUNDPAD_REQUIRE_TAG=1 corepack pnpm run validate:release`;
- the ZIP, checksum, changelog, and `RELEASE_MANIFEST.json` refer to the same
  version and commit;
- the `CodeQL` workflow passed or every new code scanning alert has been
  triaged;
- the `Dependency Review` workflow passed for dependency changes or every
  moderate-or-higher vulnerable dependency has been removed or explicitly
  accepted in the release issue;
- hardware validation records minimum supported SteamOS and Decky Loader
  versions.

For Decky Store or plugin-index submission, also require:

```bash
DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE=1 corepack pnpm run validate:release
```

## Security Reports

Use GitHub private vulnerability reporting when available. If it is not enabled
yet, move the conversation to a private channel before asking for exploit
details.

Security fixes should include:

- affected version or commit;
- impact summary;
- private reproduction details;
- fix commit;
- validation command output;
- coordinated disclosure or public advisory notes when appropriate.

## Dependency Updates

Review dependency updates in small batches. After dependency changes:

- keep the `dependencies` and `packaging` labels on Dependabot PRs;
- confirm the `Dependency Review` workflow passed before merging;
- run frozen install, checks, release validation, and license validation;
- run `corepack pnpm run licenses:generate` when dependency versions change;
- update `docs/THIRD_PARTY_NOTICES.md` if production package versions,
  source-imported packages, or license families change;
- keep Decky package updates separate from unrelated UI or backend behavior.
