# Changelog

All notable changes to DeckSoundpad should be documented here.

This project uses semantic versioning once public releases begin.

## Unreleased

### Added

- Deckbrew submission checklist and local validation gate.

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
