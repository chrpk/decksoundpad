# Security Policy

## Supported Versions

Security fixes target the current `main` branch and the latest public release.
Older releases are best effort until a stable support policy exists.

## Security Model

DeckSoundpad is a local Decky Loader plugin:

- Decky calls the Python backend in-process.
- The project does not ship a standalone LAN web UI or HTTP API.
- Audio routing is performed through local PipeWire/PulseAudio tools.
- Sound files are loaded from configured local library directories.
- Symlinks that escape configured library roots are ignored by default.
- The Decky `root` flag is requested for local input and overlay integration.

The plugin should not require permanent SteamOS root filesystem changes,
package-manager installs, or network exposure.

The current privileged-behavior rationale is maintained in
`docs/ROOT_PERMISSION_RATIONALE.md`.
The local attack-surface review is maintained in `docs/THREAT_MODEL.md`.

## Repository Secret Hygiene

Do not commit credentials, private URLs, API tokens, webhook URLs, or private
test artifacts. The repository includes a Gitleaks workflow for public CI, but
the first publication still needs a full-history scan before the repository is
made public.

`corepack pnpm run scan:secrets` performs a local high-confidence scan of
tracked files, untracked non-ignored publication files, lockfile URLs, and git
history patches. It is a release hygiene gate, not a replacement for a full
Gitleaks or GitHub secret-scanning result.

## Static Analysis

The repository includes a CodeQL workflow for JavaScript/TypeScript and Python
code scanning. Review CodeQL alerts before tagging releases or accepting changes
that affect file handling, subprocess execution, audio routing, privileged input
handling, or release packaging.

## Supply Chain Review

The repository includes a Dependency Review workflow for pull requests. It is
configured to fail if a pull request introduces moderate-or-higher vulnerable
dependencies in runtime, development, or unknown scopes.

## Logs And Privacy

DeckSoundpad logs can include local usernames, filesystem paths, audio device
names, process errors, and Decky runtime paths. Redact private information
before sharing logs in public issues.

Do not upload sound files or voice recordings unless a maintainer explicitly
asks for a minimal test asset and you have the right to share it.

The privacy and local data model is documented in `docs/PRIVACY.md`.

## Reporting A Vulnerability

Before the public repository URL is finalized, avoid posting exploit details in
public issues. Once hosted on GitHub, enable private vulnerability reporting and
use that channel for security-sensitive reports.

If private reporting is not yet enabled, open a minimal public issue asking for
a private security contact and do not include proof-of-concept details, logs
with personal paths, or exploit steps.

Include:

- Affected version or commit.
- SteamOS and Decky Loader versions.
- Whether simulation mode or real Steam Deck hardware was used.
- Impact and affected component.
- Minimal reproduction details that do not expose other users.

Expected response targets after a private channel exists:

- Initial acknowledgement within 7 days.
- Triage decision within 14 days.
- Coordinated fix plan for confirmed issues.
