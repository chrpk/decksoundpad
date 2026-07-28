# Changelog

All notable changes to DeckSoundpad should be documented here.

This project uses semantic versioning once public releases begin.

## Unreleased

### Added

- Added Decky settings dropdowns for choosing L4, L5, R4, or R5 as the
  external-overlay hotkey and selecting a discovered controller input device.
  Explicit controller selection persists via a stable evdev selector and routes
  overlay hotkey/navigation events through that device.

### Changed

- Reworked the recovery action into a full DeckSoundpad runtime restart: active
  playback, input listeners, the overlay action server, and the overlay process
  are stopped; input grabs are released; settings are reloaded; audio components
  are recreated; input devices are rediscovered; bridge workers are restarted;
  the route is rebuilt; and sounds are rescanned.
- Made restart completion operation-aware so stale route and healthcheck results
  cannot end frontend polling early, and made failed playback/router cleanup a
  reported restart failure instead of silently abandoning old resources.
- Playback timeout workers are now tracked and cancelled when playback or the
  runtime is closed.
- Shortened and reorganized user/release documentation, removed a stale
  repository-comparison report, and excluded maintainer-only material from the
  runtime ZIP.
- Made repository and secret-scan validators ignore tracked files that have
  been deleted in the working tree.
- Consolidated shared frontend status and error helpers and simplified repeated
  external-overlay ownership and navigation logic.
- Moved pnpm peer-dependency settings to `pnpm-workspace.yaml`, where current
  pnpm releases read project settings.
- Corrected frontend capability descriptions and clarified why two TypeScript
  versions appear in the third-party development dependency notice.

## 0.1.30 - 2026-07-09

### Added

- Deckbrew submission checklist and local validation gate.
- Public repository, issue tracker, and project homepage package metadata.

### Changed

- Updated the open-source readiness tracker for the final repository URL and
  remaining publication evidence.

### Security

- Hardened privileged runtime file handling against symlink replacement and
  reduced overlay sockets to owner-only access.
- Rejected symlinked or non-user-owned custom library roots/files in the
  privileged backend.
- Added a pinned Bandit gate to pull-request CI and tagged release validation.
- Dropped audio-routing, decoding, and playback subprocesses from Decky's root
  context to the Steam user before executing host audio tools.

## 0.1.29 - 2026-06-20

### Changed

- Bumped DeckSoundpad package and backend versions for a tagged GitHub release.
- Updated third-party notices for the current `@types/react` development
  dependency version.

## 0.1.28 - 2026-06-20

### Added

- Open-source readiness tracking, publication runbook, release notes template,
  and reference repository comparison.
- Contribution guide, support policy, security policy, code of conduct, issue
  templates, pull request template, labels, Dependabot configuration, and CI
  workflows.
- Release packaging checks for required runtime files, manifest metadata,
  checksum verification, docs inclusion, and forbidden development artifacts.
- Privacy, diagnostics, compatibility, maintainer, troubleshooting, release
  asset, hardware validation, threat model, and root-permission rationale docs.
- Tests for library symlink escape handling and Decky bridge behavior.

### Changed

- Current pre-public release baseline for DeckSoundpad.
- Decky in-process backend integration.
- PipeWire/PulseAudio virtual microphone routing.
- Local sound library scanning and playback controls.
- Steam Deck simulation mode for backend development.

### Security

- Documented the local-only security model, privileged root-flag rationale,
  log redaction expectations, dependency license notices, and secret-scanning
  release gates.
