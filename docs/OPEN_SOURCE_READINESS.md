# Release readiness

This file tracks only the work that still blocks a public release. Completed
implementation history belongs in Git, not in a permanent checklist.

Last checked: 2026-07-28.

## Current state

The repository exists at `https://github.com/chrpk/decksoundpad`, but it is
still private. Local CI, packaging, license, secret, and source-archive checks
exist. The plugin has not yet completed public-repository setup, hosted CodeQL
validation, or real Steam Deck hardware validation.

The project intentionally:

- ships as a Decky/GitHub ZIP, not an npm package;
- keeps `plugin.json` root flags empty;
- has no LAN HTTP API;
- runs audio and overlay subprocesses as the Steam user;
- keeps sounds outside the plugin directory;
- produces a ZIP, checksum, and `RELEASE_MANIFEST.json` from a tagged build.

See [architecture](ARCHITECTURE.md), [security](../SECURITY.md), and the
[threat model](THREAT_MODEL.md) for the design behind those decisions.

## Release blockers

- [ ] Make `https://github.com/chrpk/decksoundpad` public and verify its package
  metadata, issue links, and README links.
- [ ] Apply the settings in [repository settings](REPOSITORY_SETTINGS.md),
  including branch/tag protection and read-only workflow permissions.
- [ ] Enable private vulnerability reporting or publish a private security
  contact.
- [ ] Run and review hosted `CI`, `CodeQL`, `Dependency Review`, `Secret Scan`,
  and `Tagged Release Artifact` workflows in the public repository.
- [ ] Complete [hardware validation](HARDWARE_VALIDATION.md) on a real Steam
  Deck, including audio, microphone passthrough, sleep/resume, built-in rear
  buttons, and the external overlay.
- [ ] Record minimum supported SteamOS and Decky Loader versions in
  [compatibility](COMPATIBILITY.md).
- [ ] Prepare redacted screenshots or a demo clip and, for Deckbrew, an HTTPS
  PNG store image. Follow [release assets](RELEASE_ASSETS.md).
- [ ] Document Deckbrew code-provenance and SteamOS test evidence in the
  [submission checklist](DECKBREW_SUBMISSION_CHECKLIST.md) and
  [evidence form](DECKBREW_SUBMISSION_EVIDENCE.md).
- [ ] Open the Decky Plugin Database submission pull request.
- [ ] Build the first release from a clean `vX.Y.Z` tag and publish the exact ZIP
  and checksum produced by the tagged workflow. Do not replace them with a
  later local rebuild.

GitHub-source release and Deckbrew submission are separate gates. A GitHub
release does not need a store image; a Deckbrew submission does.

## Local release gate

Run with Node 22 and pnpm 9.15.9:

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

For a real publication decision, supply the external evidence variables and
run:

```bash
corepack pnpm run validate:publication
```

Use the [publication runbook](PUBLICATION_RUNBOOK.md) for the required evidence
and GitHub steps. Use the stricter
`DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1` gate before a plugin-index
submission.

## Ready means

DeckSoundpad is ready only when every blocker above has evidence, the full
local gate passes from a clean tagged commit, hosted security/CI workflows are
green or intentionally reviewed, hardware results match public claims, and
the published checksum belongs to the exact uploaded ZIP.
