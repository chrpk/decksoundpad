# Contributing

Thanks for helping improve DeckSoundpad. This project touches local audio
routing and privileged Decky plugin behavior, so changes should be small,
observable, and easy to test.

## Local Setup

Use Node 22 and pnpm 9.15.9. If you use nvm, run `nvm use` first to match the
repository's `.nvmrc`.

The repository uses `.editorconfig` for LF line endings, UTF-8, final newlines,
two-space TypeScript/YAML/Markdown indentation, and four-space Python
indentation. Configure your editor to honor it before broad edits.

Read `docs/ARCHITECTURE.md` before changing bridge calls, audio routing, library
scanning, external overlay behavior, release packaging, or privileged code
paths. Read `docs/BRIDGE_API.md` before adding, renaming, or reshaping Decky
callable methods.

```bash
corepack enable
corepack pnpm install
corepack pnpm run typecheck
corepack pnpm run build
corepack pnpm run test
```

Use simulation mode for backend work away from SteamOS:

```bash
DECKSOUNDPAD_SIMULATE=1 python3 -m unittest discover backend/tests
```

## Development Rules

- Keep Decky UI changes focused and compatible with Steam Deck panel layouts.
- Keep UI copy short enough for narrow Decky panels and controller navigation.
- Preserve visible focus states, disabled states, and useful error states.
- Avoid adding controls that require a keyboard for the primary Steam Deck flow.
- Keep backend calls in-process through Decky; do not add a LAN HTTP API.
- Do not make `DeckSoundpad mic` the system default input automatically.
- Do not require `pacman`, root filesystem writes, or permanent SteamOS changes.
- Prefer argument-list subprocess calls. If shell execution is unavoidable,
  keep user-controlled values out of the script body.
- Preserve the default behavior that symlinks escaping configured library roots
  are ignored.
- Add tests for routing, library scanning, config migration, and packaging
  changes that affect public behavior.

## Pull Requests

Before opening a pull request, run:

```bash
corepack pnpm run check
corepack pnpm run validate:repo
corepack pnpm run validate:deckbrew
corepack pnpm run validate:source-archive
corepack pnpm run validate:licenses
corepack pnpm run scan:secrets
corepack pnpm run package
corepack pnpm run validate:release
```

For Steam Deck behavior changes, include the SteamOS version, Decky Loader
version, plugin version, and whether the checks in
`docs/STEAMDECK_AUDIO_POC.md` and `docs/EXTERNAL_OVERLAY_POC.md` passed.

Repository triage and release-owner expectations are documented in
`docs/MAINTAINER_GUIDE.md`.

## Dependency Updates

Dependency updates should be reviewed in small groups:

- Decky packages (`@decky/api`, `@decky/ui`, `@decky/rollup`) together when
  they are released as a compatible set.
- Build tooling (`rollup`, TypeScript, Rollup plugins) separately from runtime
  behavior changes.
- Icon packages separately from UI behavior changes.

After dependency updates, run:

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm run check
corepack pnpm run package
corepack pnpm run licenses:generate
corepack pnpm run validate:licenses
```

Update `docs/THIRD_PARTY_NOTICES.md` if versions or license families change.
`corepack pnpm run licenses:generate` refreshes
`docs/THIRD_PARTY_LICENSES.md` from installed package license files.

## Secret Scanning

The public repository should keep the Gitleaks workflow enabled. For
organization-owned repositories, configure the `GITLEAKS_LICENSE` repository
secret before relying on the workflow.

The public repository should also keep the CodeQL workflow enabled for
JavaScript/TypeScript and Python code scanning. Review new CodeQL alerts before
tagging a release or merging security-sensitive changes.

Keep the Dependency Review workflow enabled. It is configured to fail if a pull
request introduces moderate-or-higher vulnerable dependencies in runtime,
development, or unknown scopes.

Install the pinned Python security tooling and run Bandit before release or
after changes to privileged Python paths:

```bash
python3 -m pip install -r requirements-security.txt
corepack pnpm run scan:python-security
```

Before first publication, run a full-history scan with one of:

```bash
gitleaks git --config .gitleaks.toml --redact --verbose
trufflehog git file://. --fail
git secrets --scan-history
```

Treat any confirmed leak as compromised: rotate the secret, remove it from
history before publication when practical, and document the remediation in the
release checklist.

## Release Changes

Release pull requests should update:

- `package.json` version
- `backend/decksoundpad/__init__.py` version
- `CHANGELOG.md`
- `docs/OPEN_SOURCE_READINESS.md` if a release blocker changes state

## Release Checklist

Before tagging a public release:

- [ ] Confirm `git status --short` is clean except intended release artifacts.
- [ ] Confirm `package.json` and `backend/decksoundpad/__init__.py` versions match.
- [ ] Update `CHANGELOG.md`.
- [ ] Run `corepack pnpm install --frozen-lockfile` from a clean checkout.
- [ ] Run `corepack pnpm run check`.
- [ ] Run `corepack pnpm run validate:repo`.
- [ ] Run `corepack pnpm run validate:deckbrew`.
- [ ] Run `corepack pnpm run validate:source-archive`.
- [ ] Run `corepack pnpm run validate:licenses`.
- [ ] Run `corepack pnpm run scan:python-security`.
- [ ] Run `corepack pnpm run scan:secrets`.
- [ ] Run `corepack pnpm run package`.
- [ ] Run `corepack pnpm run validate:release`.
- [ ] Run `corepack pnpm run validate:publication` after public repository,
  workflow, hardware, media, and release evidence exists.
- [ ] Run strict release validation after tagging:
  `DECKSOUNDPAD_REQUIRE_CLEAN_TREE=1 DECKSOUNDPAD_REQUIRE_TAG=1 corepack pnpm run validate:release`.
- [ ] Push the matching `v<version>` tag and confirm the `Tagged Release Artifact`
  workflow passed.
- [ ] Confirm the `CodeQL` workflow passed or every new alert has been triaged.
- [ ] Confirm the `Dependency Review` workflow passed for dependency changes.
- [ ] Inspect `out/DeckSoundpad-v<version>-full.zip` with `unzip -l`.
- [ ] Confirm `out/DeckSoundpad-v<version>-full.zip.sha256` was generated by
  the package or release validation command.
- [ ] Draft release notes from `docs/RELEASE_NOTES_TEMPLATE.md`.
- [ ] Run or verify a full-history secret scan.
- [ ] Complete `docs/STEAMDECK_AUDIO_POC.md` on real Steam Deck hardware.
- [ ] Complete `docs/EXTERNAL_OVERLAY_POC.md` on real Steam Deck hardware.
- [ ] Confirm README, SECURITY, and issue templates reference the final public
  repository and security contact.
- [ ] Tag the release and upload the ZIP plus checksum.
