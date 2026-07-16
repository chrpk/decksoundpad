# Reference Repository Analysis

Rechecked on 2026-07-09 while preparing DeckSoundpad for public release.

## Sources Compared

| Source | Why It Matters | Observed Pattern | Local Decision |
| --- | --- | --- | --- |
| [SteamDeckHomebrew/decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template) | Canonical Decky plugin starting point and submission guidance. | Uses the expected root files: `plugin.json`, `package.json`, `main.py` for Python backend plugins, `dist/index.js`, README, license, pnpm lockfile, and `defaults/` support. Its README calls out pnpm v9 for submission compatibility and describes ZIP distribution as a supported path. | Pin pnpm 9.15.9, keep Node/pnpm metadata aligned with CI, package a ZIP with runtime files at the plugin root, and verify required ZIP entries in `scripts/validate_release.sh`. |
| [Deckbrew plugin development docs](https://wiki.deckbrew.xyz/en/plugin-dev/getting-started) | Decky Loader documentation for plugin structure and metadata semantics. | Documents `plugin.json` as required, explains `flags`, warns that `root` should only be used when required, and lists `publish.tags`, `publish.description`, and PNG `publish.image` for store listings. It also documents `package.json` name/version expectations. | Keep `flags` empty unless a future security review explicitly authorizes elevation, and make `DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE=1` enforce store image readiness separately from GitHub source releases. |
| [SteamGridDB/decky-steamgriddb](https://github.com/SteamGridDB/decky-steamgriddb) | Mature public Decky plugin with user-facing documentation and store-install flow. | Provides a focused README with features, installation through Decky Loader, usage steps, screenshots/media, license, workflows, docs, localization, and active issue-oriented repository structure. | Keep README user-focused, require release screenshots/demo assets before broad public claims, maintain issue templates/labels, and document diagnostics/support paths for users who are not contributors. |
| [marissa999/decky-recorder](https://github.com/marissa999/decky-recorder) | Hardware-sensitive Decky plugin with Python and TypeScript that highlights long-term maintenance risk. | Public README now points users to a maintained fork and explicitly describes the ongoing burden of SteamOS, Arch Linux, Decky Loader, and diverse user setups. It still shows releases and a small plugin-oriented codebase. | Treat SteamOS/Decky behavior as unstable, keep compatibility claims evidence-based, require hardware validation per release, and keep maintainer triage/release-owner docs in the repo before public issue volume starts. |

## Requirements Derived From The Comparison

- Keep the Decky runtime ZIP small and auditable.
- Include license, README, plugin metadata, package metadata, frontend bundle,
  backend entry point, backend package files, defaults, and public support docs.
- Exclude development artifacts: `src/`, tests, `.github/`, `.git`,
  dependency folders, caches, generated archives, logs, Python bytecode, and
  local environment files.
- Keep `package.json` lowercase and versioned, but private because release
  distribution is a Decky/GitHub ZIP artifact rather than npm.
- Keep package/plugin metadata release-safe: lowercase package id, semver-like
  version, MIT license, matching author fields, no release `debug` flag, and
  focused lowercase publish tags.
- Pin pnpm 9 and make the Node version explicit across `.nvmrc`,
  `package.json`, README, CONTRIBUTING, and GitHub Actions.
- Maintain `plugin.json` store metadata, but keep `publish.image` as an
  external-release blocker until a real HTTPS PNG exists.
- Keep `root` flag rationale current and require real hardware proof before
  changing the flag.
- Include release evidence: manifest, checksum, changelog, package inspection,
  tagged workflow run, full-history secret scan, and hardware validation.
- Treat screenshots, demo clips, and logs as privacy-sensitive release assets.
- Keep public issue intake structured because audio logs can reveal usernames,
  paths, sound names, and device names.
- Document maintainer and support workflows before publishing, because
  hardware-specific Decky plugins age with SteamOS, Arch Linux, Decky Loader,
  PipeWire, and user setup changes.

## Local Coverage

Implemented local coverage:

- `scripts/validate_release.sh` builds and inspects the ZIP, checks
  `RELEASE_MANIFEST.json`, verifies checksum portability, rejects development
  artifacts, validates package/plugin metadata shape, and can require clean
  tree, matching tag, or store image.
- `scripts/validate_repo_hygiene.sh` checks community files, issue-template
  labels, blank-issue policy, workflow permissions/timeouts/concurrency,
  Dependabot coverage, current-version changelog, toolchain alignment,
  source-archive policy coverage, and Markdown links.
- `scripts/validate_source_archive.sh` verifies tracked and untracked
  publishable files against `.gitattributes` `export-ignore` rules before a
  source archive or GitHub source release is trusted.
- `.github/workflows/ci.yml` validates normal pushes and pull requests.
- `.github/workflows/codeql.yml` runs CodeQL for JavaScript/TypeScript and
  Python with the extended security and quality query suites.
- `.github/workflows/dependency-review.yml` blocks pull requests that introduce
  moderate-or-higher vulnerable dependencies in runtime, development, or unknown
  scopes.
- `.github/workflows/release.yml` validates pushed `v*` tags with strict
  clean-tree and tag gates.
- `.github/workflows/secret-scan.yml` provides full-history Gitleaks scanning
  after the public repository exists.
- `docs/HARDWARE_VALIDATION.md`, `docs/COMPATIBILITY.md`, and
  `docs/RELEASE_ASSETS.md` keep hardware, compatibility, and media claims
  evidence-based.

External evidence still required:

- final GitHub owner/name and repository metadata;
- enabled private vulnerability reporting or private security contact;
- full-history secret scanner result;
- real Steam Deck hardware validation;
- release screenshots or demo clip;
- Decky Store `publish.image` HTTPS PNG URL;
- first tagged workflow run;
- first GitHub release containing ZIP and checksum.
