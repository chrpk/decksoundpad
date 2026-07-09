# Repository Settings Baseline

Use this checklist after creating the public GitHub repository and before
accepting outside pull requests. It keeps repository settings aligned with the
local release gates.

## Metadata

- Repository name: `decksoundpad`, unless a final owner-specific name is chosen
  in `docs/OPEN_SOURCE_READINESS.md`.
- Description: `Decky Loader soundboard that mixes sounds with the real microphone into a virtual mic.`
- Topics: `decky`, `steam-deck`, `decky-loader`, `soundboard`, `pipewire`,
  `microphone`, `steamos`.
- Default branch: `main`.
- Wikis and Projects: disabled unless maintainers commit to triaging them.
- Discussions: optional; if enabled, keep security reports routed through
  `SECURITY.md`, not public discussion threads.

## Security Features

Enable before the first public release:

- Dependency graph.
- Dependabot alerts.
- Code scanning alerts for the `CodeQL` workflow.
- Secret scanning and push protection when available for the repository.
- Private vulnerability reporting, or a private security contact documented in
  `SECURITY.md`.

Repository secrets should stay empty unless a workflow explicitly needs one.
The current expected secret is only `GITLEAKS_LICENSE`, and only for
organization-owned repositories where the Gitleaks action requires it.

## Actions Policy

- Default workflow token permissions: read-only.
- Fork pull request approval: require approval for first-time contributors.
- Required pull-request workflows after their first successful run:
  - `CI`
  - `CodeQL`
  - `Dependency Review`
  - `Secret Scan`, once the full-history secret-scan setup is confirmed
- Required tagged-release workflow before publishing a GitHub Release:
  - `Tagged Release Artifact`

Keep workflow definitions consistent with `corepack pnpm run validate:repo`:
actions pinned to approved major versions, no `pull_request_target`, no broad
write permissions outside the release publisher, disabled checkout credential
persistence, timeouts, and concurrency.

## Branch And Tag Protection

Protect `main` with branch protection or repository rules:

- Require pull requests before merging.
- Require conversation resolution.
- Block force pushes.
- Require linear history if the project adopts squash or rebase merges.
- Require the pull-request workflows listed above once initial runs pass.

Protect release tags matching `v*`:

- Restrict tag creation to maintainers.
- Block tag deletion and force updates.
- Create or move a tag only after strict local release validation passes.

## Issues And Labels

- Keep blank issues disabled.
- Apply `.github/labels.yml` with `corepack pnpm run labels:sync` after
  publication.
- Keep security reports out of public issues. Public issue templates should
  continue requiring reporters to confirm they removed exploit details, private
  paths, usernames, and unredacted logs.

## Release Evidence

Before publishing each GitHub Release, the release issue should include:

- `corepack pnpm run validate:release` result from a clean checkout.
- `corepack pnpm run scan:python-security` result from the pinned Bandit version.
- `corepack pnpm run validate:publication` result after external evidence is
  supplied.
- `Tagged Release Artifact` workflow URL.
- `CodeQL`, `Dependency Review`, and full-history secret-scan results.
- ZIP filename and SHA-256 checksum from the GitHub Release assets published by
  the tagged workflow.
- Steam Deck hardware validation evidence.
- Decky Store image URL when submitting to the Decky plugin index.
