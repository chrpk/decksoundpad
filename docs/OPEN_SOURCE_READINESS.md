# Open Source Readiness

This document tracks what is required before DeckSoundpad is treated as a
public open-source project instead of a local prototype.

## External Baseline

Compared references, rechecked on 2026-06-20:

- [SteamDeckHomebrew decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template):
  establishes the expected Decky plugin shape, frontend build, `plugin.json`,
  package metadata, and plugin submission workflow.
- [Decky Loader plugin development docs](https://wiki.deckbrew.xyz/en/plugin-dev/getting-started):
  confirm current plugin structure, `plugin.json` fields, root-flag semantics,
  `publish.image` expectations for store listings, and the `defaults/` folder
  convention. The wiki's pnpm section still mentions older lockfile guidance,
  while the current template recommends pnpm v9; re-check this before a Decky
  Store submission.
- [SteamGridDB decky-steamgriddb](https://github.com/SteamGridDB/decky-steamgriddb):
  a mature Decky plugin with public README, MIT license, package metadata, and
  repository-centered distribution.
- [marissa999 decky-recorder](https://github.com/marissa999/decky-recorder):
  a Decky plugin that documents installation, usage, known limitations, and
  hardware-specific behavior.
- [GitHub community health documentation](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file):
  baseline for public contribution files such as README, LICENSE,
  CONTRIBUTING, SECURITY, issue templates, and code of conduct.

A deeper comparison matrix is maintained in `docs/REFERENCE_REPOS.md`.

## Comparison Findings And Local Decisions

- Decky distribution expects a small plugin ZIP with runtime files at the
  plugin root, including `dist/index.js`, `package.json`, `plugin.json`,
  `main.py` when a Python backend is used, README, and license. Local decision:
  `scripts/validate_release.sh` now verifies required runtime entries and fails
  if development artifacts such as `src/`, tests, `node_modules`, logs, or
  hidden repository state enter the ZIP. The ZIP also includes a generated
  `RELEASE_MANIFEST.json` that records package version, backend version, plugin
  API version, flags, artifact name, source commit, dirty state, and generation
  time. Packaging now avoids `rsync` and preflights required standard commands
  before reading package metadata so fresh contributor and CI environments fail
  early with clear errors. Packaging also requires either `shasum` or
  `sha256sum`, so `corepack pnpm run package` always produces a ZIP and matching
  `.sha256` file.
- Mature Decky plugins use truthful package metadata and issue links once the
  public repository exists. Local decision: do not publish placeholder
  `repository`, `bugs`, or `homepage` values; add them only after the final
  owner/name is chosen. Also keep `package.json` private because DeckSoundpad
  is distributed as a Decky/GitHub ZIP artifact, not an npm package. Release
  validation now enforces lowercase package id, semver-like version, MIT
  license, author consistency, focused lowercase keywords/tags, short
  descriptions, and no `debug` flag in `plugin.json`. Repository hygiene
  validation also checks the MIT license text and a dated structured changelog
  entry for the current package version.
- Decky Store metadata can include a PNG `publish.image` for the store listing.
  Local decision: keep GitHub source release validation independent from store
  submission validation, but enforce the image with
  `DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE=1` before any plugin-index submission.
- Public screenshots and demo clips need privacy and naming rules. Local
  decision: add `docs/RELEASE_ASSETS.md` for required release media, redaction
  rules, and Decky Store image expectations. Release media may be committed or
  attached to GitHub Releases, but it is excluded from the runtime plugin ZIP.
- Privileged Decky plugins need a clear user-facing reason for the root flag.
  Local decision: keep `flags: ["root"]` for now, document every privileged
  path, and require hardware validation before either removing or permanently
  justifying it.
- Hardware-bound Decky plugins become hard to maintain when SteamOS, Arch Linux,
  or Decky Loader behavior changes. Local decision: require release-candidate
  hardware evidence, minimum supported SteamOS/Decky versions, and a
  troubleshooting matrix before calling the project ready. Compatibility claims
  are centralized in `docs/COMPATIBILITY.md`.
- Public open-source repositories need contribution and security workflows that
  are live, not just present in files. Local decision: add community files,
  templates, CI, secret scanning, labels, and a publication runbook, but keep
  repo-settings items unchecked until GitHub confirms them. Local validation
  now checks required community files, label references, workflow permissions,
  workflow timeouts, Dependabot coverage, current-version changelog entry, and
  local Markdown links. It also checks that the code of conduct includes scope,
  enforcement, private-reporting guidance, and an interim route that does not
  require publishing sensitive details before the final maintainer contact
  exists.
- Public CI should not start on deprecated action runtimes. Local decision:
  keep workflow actions pinned to explicit, current major versions checked on
  2026-06-20, and let Dependabot propose future major updates for review.
- Public users need a single place to understand what local files, logs, audio
  metadata, and device names the plugin can touch. Local decision: add
  `docs/PRIVACY.md` and link it from README, SECURITY, and SUPPORT.
- Public users need safe lifecycle guidance beyond a one-line install command.
  Local decision: add `docs/INSTALLATION.md` covering release ZIP installs,
  updates, rollback, uninstall, local data review, and recovery without telling
  users to delete their sound libraries.
- Public issue reports need repeatable diagnostic instructions that avoid
  leaking private files, device names, or logs. Local decision: add
  `docs/DIAGNOSTICS.md` and link it from README, SUPPORT, troubleshooting,
  hardware validation, and the bug template. Blank issues are disabled so
  public reports use templates with required security-routing, redaction, and
  diagnostics acknowledgements.
- Privileged local plugins need a concrete threat model before public issue
  reports and contributions begin. Local decision: add `docs/THREAT_MODEL.md`
  covering trust boundaries, threats, mitigations, and release-review checks.
- Public contributors need a code map before reviewing privileged local changes.
  Local decision: add `docs/ARCHITECTURE.md` covering entry points, frontend and
  backend modules, data flows, local files/logs, privileged behavior,
  simulation, release artifacts, and architecture-sensitive review triggers.
- Public contributors need a stable Decky bridge contract before changing the
  frontend/backend boundary. Local decision: add `docs/BRIDGE_API.md` covering
  callable names, request/response payloads, fallbacks, timeouts, logging, and
  required test/doc updates.
- Public maintainers need consistent triage and release-promotion rules before
  issues and pull requests open. Local decision: add `docs/MAINTAINER_GUIDE.md`
  and link it from README and CONTRIBUTING. Dependabot PRs are labeled as
  `dependencies` and `packaging` so dependency work is visible in public triage.
- Public source archives should not depend on platform-specific line endings or
  generated artifacts. Local decision: add `.gitignore` for local working-tree
  artifacts and `.gitattributes` with LF text normalization, binary file
  handling, and `export-ignore` entries for local build output, caches, logs,
  environment files, and virtual environment directories. Add `.editorconfig`
  so common editors use the same LF, UTF-8, final-newline, and indentation
  defaults before contributors touch broad file sets.
- Tagged release builds need CI evidence that the published ZIP was produced
  from a clean tagged commit. Local decision: add a tag-only GitHub Actions
  workflow that runs strict release validation and uploads the package-version
  ZIP plus checksum as a workflow artifact before a GitHub Release is
  published. Release notes must treat the checksum as evidence for the exact
  uploaded ZIP because the release manifest includes build-specific
  `generatedAt` evidence.

## Current State

Already present:

- MIT license.
- Decky plugin metadata in `plugin.json`.
- `package.json` marked private to prevent accidental npm publication.
- TypeScript Decky UI build through Rollup.
- Python backend tests under `backend/tests`.
- Package script that builds a distributable ZIP under `out/`.
- Local-only backend design with no LAN HTTP API.
- Default symlink escape protection for configured sound libraries.

Added during open-source preparation:

- `CONTRIBUTING.md`
- `SECURITY.md`
- `SUPPORT.md`
- `CODE_OF_CONDUCT.md`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- GitHub Actions CI workflow.
- CodeQL code scanning workflow.
- Tagged release artifact workflow.
- GitHub issue and pull request templates.
- Dependabot configuration.
- Compatibility, privacy, maintainer, release, troubleshooting, and hardware
  validation docs.
- Installation, update, rollback, uninstall, and recovery guide.
- Publication readiness validation script for final public-release evidence.
- Reference repository comparison in `docs/REFERENCE_REPOS.md`.
- This readiness tracker.

## Release Blockers

- [ ] Choose the final public repository owner/name.
  - Evidence needed: `git remote -v` points to the public repository.
  - Update after decision: `package.json` repository, bugs, homepage fields;
    README badges; SECURITY reporting text; issue template contact links.
  - Current support: `docs/PUBLICATION_RUNBOOK.md` lists the exact repository
    metadata and files to update after the remote exists.
- [ ] Enable private vulnerability reporting or publish a private security
  contact.
  - Evidence needed: GitHub security settings or a dedicated contact address.
  - Why it matters: the plugin has privileged local behavior and should not
    receive exploit details in public issues.
  - Current support: `docs/PUBLICATION_RUNBOOK.md` lists the required GitHub
    security settings before accepting public reports.
- [x] Verify the Decky submission toolchain version.
  - Evidence: upstream Decky template states pnpm v9 is expected for plugin
    submission compatibility; this repo now pins `pnpm@9.15.9` and uses
    lockfile v9. Local pnpm 9 install/build/test/package validation completed
    on 2026-06-20.
  - Evidence: `.nvmrc`, GitHub Actions workflows, README, CONTRIBUTING, and
    `package.json` now align on Node 22. `corepack pnpm run validate:repo`
    fails if `.nvmrc`, `package.json`, or setup-node workflow versions drift.
  - Caveat: the Deckbrew wiki still contains older pnpm lockfile guidance.
    Reconfirm the store CI requirement before submitting to a Decky plugin
    index.
- [ ] Run hardware validation on a real Steam Deck.
  - Evidence needed: checked-off results in `docs/STEAMDECK_AUDIO_POC.md` and
    `docs/EXTERNAL_OVERLAY_POC.md` for the release candidate.
  - Must include: SteamOS version, Decky Loader version, whether the real mic
    is detected, and whether `DeckSoundpad mic` works in at least one voice app.
  - Current support: `docs/HARDWARE_VALIDATION.md` provides a release-candidate
    evidence template.
- [ ] Create release screenshots or a short demo clip.
  - Evidence needed: assets committed or attached to the first public release.
  - Must show: Decky panel, sound grid, settings, and voice app input selection.
  - Current support: `docs/HARDWARE_VALIDATION.md` defines required screenshot
    and demo captures.
  - Current support: `docs/RELEASE_ASSETS.md` defines privacy, naming, and
    release-note expectations for screenshots and demo clips.
  - Current support: `scripts/package_plugin.sh` packages Markdown docs only,
    and `corepack pnpm run validate:release` rejects `docs/assets/` or docs
    media files inside the plugin ZIP.
- [ ] Add a Decky Store publish image before plugin index submission.
  - Evidence needed: `plugin.json` `publish.image` points to an HTTPS PNG URL.
  - Current support: `DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE=1 corepack pnpm run
    validate:release` enforces this when validating a store submission.
  - Current support: `docs/RELEASE_ASSETS.md` defines image-content rules and
    forbids placeholder image URLs.
  - This is not required for a GitHub source release, but is required before
    treating the project as ready for a Decky Store or plugin-index listing.
- [ ] Confirm the `root` flag is still required.
  - Evidence needed: hardware validation showing which input/overlay features
    fail without root, or a patch removing the flag.
  - Documentation required: README and SECURITY must keep the rationale current.
  - Current support: `docs/ROOT_PERMISSION_RATIONALE.md` documents the static
    code paths that use privileged local device and socket operations.
- [ ] Publish first release artifact with checksum.
  - Evidence needed: GitHub release containing `DeckSoundpad-vX.Y.Z-full.zip`
    and SHA-256 checksum.
  - Current support: `scripts/package_plugin.sh` writes
    `DeckSoundpad-vX.Y.Z-full.zip.sha256` and fails early if neither `shasum`
    nor `sha256sum` is available.
  - Current support: `DECKSOUNDPAD_REQUIRE_CLEAN_TREE=1
    DECKSOUNDPAD_REQUIRE_TAG=1 corepack pnpm run validate:release` enforces a
    clean worktree and matching `vX.Y.Z` git tag for actual release builds.
  - Current support: `.github/workflows/release.yml` runs the strict tagged
    release gate for `v*` tag pushes and uploads the ZIP plus checksum as a
    workflow artifact.
  - Current support: `docs/RELEASE_NOTES_TEMPLATE.md` captures release
    checksum, manifest, hardware evidence, root-flag status, asset locations,
    full-history secret-scan result, and tagged workflow URL.
  - Current support: `docs/RELEASE_NOTES_TEMPLATE.md` and
    `docs/PUBLICATION_RUNBOOK.md` state that the checksum belongs to the exact
    uploaded ZIP from the strict tagged build, not a later local rebuild.
  - Current support: `docs/PUBLICATION_RUNBOOK.md` documents the release upload
    and release-note requirements.
  - Current support: `corepack pnpm run validate:publication` fails until the
    final public repository metadata, repository settings, hosted workflow
    results, full-history secret scan, hardware validation, release media,
    published ZIP, checksum, minimum supported versions, and root-flag decision
    have concrete evidence.
  - Release must be built from a clean tree and matching git tag.

## High Priority Todo

- [x] Replace the empty package repository URL with truthful metadata handling.
  - Current action: removed the invalid empty `repository.url`.
  - Remaining action: add real repository/bugs/homepage fields once the public
    URL exists.
- [x] Prevent accidental npm publication.
  - Evidence: `package.json` has `"private": true`.
  - Evidence: `corepack pnpm run validate:release` fails if the private flag is
    removed.
  - Distribution path: GitHub/Decky release ZIP plus checksum.
- [x] Add community health files for public collaboration.
  - Evidence: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
    `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`.
  - Evidence: `corepack pnpm run validate:repo` checks required community files
    issue-template label references, changelog version evidence, required docs,
    local Markdown links, and local file references inside GitHub issue and pull
    request templates.
  - Evidence: `corepack pnpm run validate:repo` checks that
    `CODE_OF_CONDUCT.md` includes scope, expected behavior, unacceptable
    behavior, enforcement authority, private-reporting guidance, and an interim
    minimal-public-issue route for sensitive conduct reports before the final
    maintainer contact exists.
  - Evidence: `corepack pnpm run validate:repo` checks that the pull request
    template, release checklist, and contributor guide list the core validation
    commands.
  - Evidence: `.github/ISSUE_TEMPLATE/config.yml` disables blank issues so
    public reports go through structured forms.
  - Evidence: the bug report template requires reporters to confirm they did
    not include private security details, exploit steps, private paths,
    usernames, or unredacted logs.
  - Evidence: the bug report template requires Steam Deck model and
    installation source so hardware-specific reports can be triaged against
    release ZIPs, local builds, or plugin-index installs.
- [x] Add baseline CI for build, tests, and packaging.
  - Evidence: `.github/workflows/ci.yml`.
  - Evidence: `.github/workflows/codeql.yml` runs CodeQL analysis for
    JavaScript/TypeScript and Python on pushes, pull requests, a weekly
    schedule, and manual dispatch.
  - Evidence: `.github/workflows/dependency-review.yml` runs on pull requests
    and fails dependency changes that introduce moderate-or-higher vulnerable
    dependencies in runtime, development, or unknown scopes.
  - Evidence: `corepack pnpm run validate:repo` checks read-only workflow
    permissions, concurrency, timeouts, required labels, Dependabot coverage for
    npm and GitHub Actions, Dependabot labels, and disabled checkout credential
    persistence.
  - Evidence: `corepack pnpm run validate:repo` restricts
    `security-events: write` to the CodeQL workflow and checks CodeQL language
    coverage, query suite, schedule, and action pins.
  - Evidence: `corepack pnpm run validate:repo` checks that workflow actions are
    pinned and use the current major lines verified on 2026-06-20:
    `actions/checkout@v7`, `actions/setup-node@v6`,
    `actions/setup-python@v6`, `actions/upload-artifact@v7`,
    `actions/dependency-review-action@v5`, `pnpm/action-setup@v6`,
    `github/codeql-action/init@v4`, `github/codeql-action/analyze@v4`, and
    `gitleaks/gitleaks-action@v3`.
  - Evidence: `corepack pnpm run validate:repo` checks that workflows using
    `setup-node` pnpm caching run `pnpm/action-setup` first, pin pnpm to
    `9.15.9`, bind cache keys to `pnpm-lock.yaml`, and leave dependency
    installation to `validate:release`.
  - Evidence: `corepack pnpm run validate:repo` checks package script
    references, shell-script shebangs, `set -euo pipefail`, shell syntax, and
    executable permissions for directly invoked scripts.
  - Evidence: `docs/REPOSITORY_SETTINGS.md` defines the public repository
    settings baseline for security features, Actions permissions, required
    workflows, branch protection, tag protection, labels, and release evidence.
  - Remaining validation: first CI, CodeQL, and Dependency Review runs after
    repository publication.
- [x] Add tagged release artifact CI.
  - Evidence: `.github/workflows/release.yml` runs strict release validation on
    pushed `v*` tags with clean-tree and tag checks enabled, then uploads the
    current package-version ZIP and checksum as workflow artifacts.
  - Evidence: `corepack pnpm run validate:repo` checks all workflows for
    read-only contents permissions, concurrency, timeouts, disabled checkout
    credential persistence, exact current-version artifact upload paths, and
    absence of `pull_request_target`.
  - Remaining validation: first tag workflow run after repository publication.
- [x] Add automated committed-secret scanning.
  - Evidence: `.github/workflows/secret-scan.yml` runs Gitleaks against full
    history with `.gitleaks.toml`.
  - Remaining validation: configure `GITLEAKS_LICENSE` if the repo is owned by
    an organization, then review the first workflow result.
- [x] Document privileged behavior and local-only security model.
  - Evidence: README and SECURITY updates.
  - Evidence: `docs/THREAT_MODEL.md` documents trust boundaries for local file
    scanning, subprocess playback, audio routing, Unix sockets, input devices,
    support logs, and release artifacts.
- [x] Add contributor architecture and code map documentation.
  - Evidence: `docs/ARCHITECTURE.md` documents runtime shape, entry points,
    frontend modules, backend modules, status/settings, library scanning,
    playback/audio routing, external overlay, local files/logs, privileged
    behavior, simulation, build/release artifacts, and architecture-sensitive
    review triggers.
  - Evidence: `docs/BRIDGE_API.md` documents the Decky callable contract,
    status/settings/library payloads, startup/repair semantics, fallbacks,
    logging privacy, and bridge change checklist.
  - Evidence: README, CONTRIBUTING, THREAT_MODEL, and MAINTAINER_GUIDE link to
    or reference the architecture guide.
- [x] Add tests for symlink escape protection.
  - Evidence: backend library tests for default deny and explicit allow.
- [x] Run a dependency/license review before first release.
  - Evidence: `docs/THIRD_PARTY_NOTICES.md`, generated from
    `corepack pnpm licenses list` and source import review on 2026-06-20.
  - Evidence: `corepack pnpm run validate:licenses` checks that every
    production package reported by `corepack pnpm licenses list --prod --json`,
    every package directly imported from `src/`, and every direct development
    dependency has a row in `docs/THIRD_PARTY_NOTICES.md`.
  - Evidence: `corepack pnpm run validate:licenses` rejects stale production
    rows, stale direct-development rows, and stale transitive license-family
    entries in `docs/THIRD_PARTY_NOTICES.md`.
  - Evidence: `docs/THIRD_PARTY_LICENSES.md` is generated from installed
    production and source-imported package license files, and
    `corepack pnpm run validate:licenses` fails if it is stale.
  - Evidence: `corepack pnpm run validate:licenses` also checks
    `react-icons/fa` imports and requires `docs/THIRD_PARTY_NOTICES.md` to
    list the imported Font Awesome icons and CC BY 4.0 attribution.
  - Evidence: `corepack pnpm run validate:licenses` checks LGPL source
    availability rows for production dependencies and frontend source imports
    against installed package metadata, including upstream HTTPS source URLs and
    the no-local-third-party-modifications statement.
  - Evidence: `corepack pnpm run package` runs the license notice validation
    before staging a release ZIP, so stale third-party license files cannot be
    packaged by the standalone package command.
  - Expected dependencies: Decky packages, React, React icons, Rollup, and
    TypeScript.
- [ ] Run a secret scan before making the repository public.
  - Evidence needed: clean `git-secrets`, `gitleaks`, or GitHub secret scanning
    result against full history.
  - Current support: Gitleaks workflow and config have been added, but no local
    scanner binary is installed in this environment, so this remains unchecked.
  - Current support: `corepack pnpm run scan:secrets` performs a local
    high-confidence scan of tracked files, untracked non-ignored publication
    files, lockfile URLs, and git-history patches for common private keys,
    cloud keys, GitHub, GitLab, npm, Slack, Google, OpenAI-style, and Stripe
    tokens. This is useful release hygiene, but it does not replace Gitleaks or
    GitHub secret scanning.
  - Current evidence: `corepack pnpm run scan:secrets` passed locally on
    2026-06-20.
- [x] Confirm the packaged ZIP contains only needed runtime files.
  - Evidence needed: inspected ZIP file list from `corepack pnpm run package`.
  - Current evidence: package inspection on 2026-06-20 showed runtime files,
    public docs, metadata, defaults, `dist`, `main.py`, and backend package
    files only.
  - Current evidence: `corepack pnpm run validate:release` passed on
    2026-06-20, including frozen install, typecheck, build, tests, package
    inspection, repository hygiene validation, and checksum verification.
  - Current evidence: `corepack pnpm run validate:release` checks
    `RELEASE_MANIFEST.json` inside the ZIP for matching package/backend version,
    artifact name, Decky API version, exact `plugin.json` flags, exact git
    `HEAD` commit, current dirty-state, and timestamp.
  - Current evidence: `corepack pnpm run validate:release` now fails on
    frontend/backend version mismatch, missing required ZIP files, forbidden
    development artifacts in the ZIP, non-portable checksum paths, incomplete
    package metadata, malformed Decky/package metadata, incomplete Decky publish
    metadata, and optional strict release gates for clean tree/tag/publish image
    when those environment variables are set.
  - Current evidence: `corepack pnpm run validate:release` checks that the
    frontend bundle replaced build metadata placeholders and includes the
    package version in the visible Decky panel build metadata.
  - Current evidence: `corepack pnpm run validate:repo` checks that packaging
    avoids undeclared `rsync` usage, preflights required commands, and removes
    Python bytecode/cache files from the staged backend.
  - Current evidence: `corepack pnpm run validate:repo` checks that package and
    release validation command preflights run before Node-based version parsing.
  - Current evidence: `corepack pnpm run validate:repo` checks that package and
    release validation fail instead of silently skipping SHA-256 checksum
    generation or verification when checksum tooling is missing.
  - Current evidence: `corepack pnpm run validate:release` rejects Python
    bytecode variants (`*.pyc`, `*.pyo`, `*.pyd`) and `__pycache__` directories
    if they enter the plugin ZIP.
  - Must exclude: node_modules, caches, tests, local logs, hidden state,
    screenshots not meant for release.
- [x] Add a release checklist.
  - Evidence: `CONTRIBUTING.md` covers version sync, changelog, clean install,
    checks, package inspection, checksum, tag, and Deck hardware validation.
  - Evidence: `.github/ISSUE_TEMPLATE/release_checklist.yml` gives each release
    candidate a structured tracking issue.
  - Evidence: `docs/RELEASE_NOTES_TEMPLATE.md` provides the release-note
    evidence format for checksums, manifests, hardware validation, assets,
    secret-scan status, and tagged workflow runs.
  - Evidence: `corepack pnpm run validate:repo` checks that the release notes
    template and publication runbook keep checksum provenance and release
    evidence fields.
  - Evidence: `corepack pnpm run validate:repo` fails if `CHANGELOG.md` does
    not include an `Unreleased` section, a dated heading for the current
    `package.json` version, and baseline release evidence sections.
- [x] Add a final publication readiness gate.
  - Evidence: `corepack pnpm run validate:publication` reports unresolved
    public-launch blockers and only runs local release validation after
    external evidence variables for repository settings, private vulnerability
    intake, full-history secret scanning, hardware validation, media, workflow
    runs, artifact, checksum, supported versions, and root-flag decision are
    present.
  - Evidence: `corepack pnpm run validate:repo` checks that the publication
    gate and publication runbook list the required evidence variables.
- [x] Add maintainer triage and release-owner guidance.
  - Evidence: `docs/MAINTAINER_GUIDE.md` documents label use, issue flow, PR
    review, release promotion, security report handling, and dependency update
    expectations.
  - Evidence: README and CONTRIBUTING link to the maintainer guide.
- [x] Add source archive hygiene policy.
  - Evidence: `.gitattributes` sets LF text normalization, marks binary asset
    types, and excludes local generated output, caches, logs, `.env`, and
    virtual environment directories from source archives.
  - Evidence: `.gitignore` ignores dependency folders, generated output,
    caches, logs, `.env`, Python bytecode, and virtual environments.
  - Evidence: `.editorconfig` records LF, UTF-8, final-newline, two-space
    frontend/docs config indentation, and four-space Python indentation.
  - Evidence: `corepack pnpm run validate:repo` checks key `.gitignore`,
    `.gitattributes`, and `.editorconfig` entries.
  - Evidence: `corepack pnpm run validate:source-archive` checks tracked and
    untracked publishable files against `.gitattributes` `export-ignore`
    decisions, requires public source files to remain included, and rejects
    generated output, dependency folders, caches, logs, `.env`, Python bytecode,
    and virtual environments from the source archive candidate.

## Medium Priority Todo

- [ ] Add screenshots to README once the UI is stable.
- [x] Add a troubleshooting matrix for common PipeWire/PulseAudio failures.
  - Evidence: `docs/TROUBLESHOOTING.md`.
- [x] Add install, update, rollback, and uninstall guidance.
  - Evidence: `docs/INSTALLATION.md` explains release ZIP install, checksum
    verification, update, rollback, uninstall, local data review, and recovery.
  - Evidence: README and release notes link to the installation guide.
  - Evidence: `corepack pnpm run validate:repo` checks that the guide remains
    present and covers install/update/uninstall/rollback/recovery, version
    metadata, sound-library preservation, and support logs.
- [x] Add safe diagnostic collection guidance.
  - Evidence: `docs/DIAGNOSTICS.md` lists required environment details, audio
    routing commands, log locations, redaction rules, sound-library checks,
    overlay checks, and security-report routing.
  - Evidence: README, SUPPORT, TROUBLESHOOTING, HARDWARE_VALIDATION, and the
    bug report template point users to the diagnostics guide.
- [ ] Add a minimum supported SteamOS and Decky Loader version.
  - Current support: `docs/HARDWARE_VALIDATION.md` records the lowest validated
    SteamOS and Decky Loader versions for release notes.
  - Current support: `docs/COMPATIBILITY.md` publishes compatibility claims and
    keeps unknown values explicit until real hardware validation provides
    evidence.
- [x] Add contributor guidance for UI copy, accessibility, and Steam Deck panel
  constraints.
- [x] Add optional formatting/lint checks if the project adopts a formatter.
  - Current decision: no formatter has been adopted. A strict TypeScript
    `typecheck` gate is now part of `corepack pnpm run check` and CI.
- [x] Add dependency update policy for Decky API/UI packages.
  - Evidence: `.github/dependabot.yml` labels dependency PRs with
    `dependencies` and `packaging`.
  - Evidence: `.github/labels.yml` defines the `dependencies` label, and
    `corepack pnpm run validate:repo` fails if required labels or Dependabot
    labels drift.
- [x] Decide whether bundled sample sounds should exist. If yes, ensure every
  bundled audio asset has clear licensing and attribution.
  - Current decision: no bundled audio assets are shipped in `defaults/`.
    Future bundled sounds need license and attribution before release.
- [x] Add a privacy note explaining that logs may contain local paths and audio
  device names.
  - Evidence: `docs/PRIVACY.md` documents local files read/written, log
    contents, network expectations, and what users should redact before public
    support requests.
  - Evidence: README, SECURITY, and SUPPORT link to the privacy document.
- [ ] Add issue labels after GitHub publication: `bug`, `documentation`,
  `enhancement`, `audio-routing`, `steam-deck`, `security`,
  `good-first-issue`.
  - Current support: `.github/labels.yml` defines the intended label set; apply
    it after the public repository exists.
  - Current support: `corepack pnpm run labels:sync` applies labels through
    GitHub CLI after `gh auth status` succeeds.
  - Current support: `docs/PUBLICATION_RUNBOOK.md` lists the required labels
    and dry-run command.

## Technical Risk Register

- Root Decky flag:
  - Risk: public users need clear justification for privileged plugin behavior.
  - Mitigation: document why it is requested and re-check whether features can
    be split into optional privileged paths.
- Audio routing:
  - Risk: SteamOS/PipeWire behavior changes can break module loading.
  - Mitigation: keep parser tests, hardware POC, and repair workflow current.
- Local file playback:
  - Risk: path traversal or symlink escapes could load unexpected files.
  - Mitigation: library roots are resolved and symlink escapes are denied by
    default; tests cover both default deny and explicit allow.
- Subprocess playback:
  - Risk: shell quoting mistakes can become command injection bugs.
  - Mitigation: most commands use argument lists; shell fallback passes paths
    as positional parameters and should remain covered by command tests.
- Public logs:
  - Risk: logs can include local usernames, paths, and audio device names.
  - Mitigation: document privacy expectations before asking users for logs.

## Completion Criteria

DeckSoundpad is ready to publish when:

1. All release blockers above are checked off with evidence.
2. `corepack pnpm run check` passes from a clean install.
3. `corepack pnpm run package` produces an inspected ZIP.
4. A real Steam Deck validates audio routing and external overlay docs.
5. Community files and issue templates are live in the public repository.
6. The public release has a tag, changelog entry, ZIP artifact, and checksum.
