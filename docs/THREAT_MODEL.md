# Threat Model

This threat model covers DeckSoundpad as a local Decky Loader plugin that
scans sound files, manages local audio routing, and optionally monitors Steam
Deck input devices for overlay controls.

The implementation map and module boundaries are maintained in
`docs/ARCHITECTURE.md`.

## Security Goals

- Keep all control paths local to Decky and the local backend.
- Avoid network exposure, telemetry, remote control, and remote asset loading.
- Prevent configured sound libraries from escaping into unexpected filesystem
  locations by default.
- Avoid command injection in playback and audio-routing subprocesses.
- Keep device access optional, documented, and bounded to the normal user.
- Prevent public support workflows from leaking private paths, device names,
  sound filenames, or credentials.

## Trust Boundaries

| Boundary | Trusted Side | Untrusted Or Sensitive Side |
| --- | --- | --- |
| Decky UI to backend | In-process Decky bridge methods | User-triggered UI actions and settings |
| Sound library scanning | Configured local library roots | Symlinks, filenames, and user-controlled files |
| Audio routing | Local PipeWire/PulseAudio commands | Host audio state and command output |
| External overlay | Backend-owned Unix sockets and process args | Local socket messages and overlay actions |
| Input monitoring | Steam Deck `/dev/input` and `/dev/hidraw*` reads | Device names, HID reports, and permissions |
| Logs and support | Maintainer-reviewed redacted snippets | Local usernames, paths, sound names, and device names |
| Release artifacts | Tagged build, ZIP, checksum, manifest | Dirty worktree output or stale package contents |

## Main Threats And Mitigations

### Local File Disclosure

Threat: a sound library symlink or path could make the plugin index or play
files outside configured library roots.

Mitigations:

- symlinks escaping configured library roots are ignored by default;
- configured library roots must be real directories owned by the Steam user,
  and non-user-owned sound files are rejected;
- tests cover default-deny and explicit opt-in symlink behavior;
- privacy docs warn that filenames and paths can appear in logs.

### Command Injection

Threat: sound paths, device names, or user-controlled values could be
interpolated into shell commands.

Mitigations:

- playback and routing code should prefer argument-list subprocess calls;
- shell fallback paths must keep user-controlled values out of the script body;
- audio subprocesses run as the normal Steam user's UID, GID, and supplementary
  groups before executing host tools;
- release review requires careful inspection of subprocess construction.

### Unnecessary Device Access

Threat: optional device monitoring could expand into an implicit privilege
request or access devices outside the feature's scope.

Mitigations:

- device paths are documented in `docs/ROOT_PERMISSION_RATIONALE.md`;
- release validation rejects a `root` flag in `plugin.json`;
- direct input and HID monitors are disabled when the normal user lacks access;
- enabling diagnostics never invokes an elevation helper.

### Unsafe Local Sockets

Threat: local overlay sockets could accept unexpected commands or expose more
control than intended.

Mitigations:

- sockets are Unix-domain local resources, not LAN listeners;
- overlay sockets use owner-only filesystem permissions;
- overlay actions are constrained to known UI commands;
- the project must not add a LAN HTTP API without a separate design review.

### Privileged File Writes

Threat: a Steam user could replace a state or log file with a symlink and cause
the root Decky backend to overwrite, chown, or chmod a privileged target.

Mitigations:

- configuration, state, cache, and log files are opened with `O_NOFOLLOW` and
  verified as regular files before use;
- runtime directories are opened with `O_DIRECTORY | O_NOFOLLOW` before any
  ownership or mode change;
- Unix socket ownership and modes are changed without following symlinks;
- regression tests verify that symlink targets remain unchanged.

### Sensitive Logs

Threat: public logs can leak local usernames, filesystem paths, audio device
names, sound filenames, or runtime paths.

Mitigations:

- `docs/PRIVACY.md`, `SUPPORT.md`, and `SECURITY.md` require redaction before
  public sharing;
- logs and issue templates warn users not to upload private sound files or
  voice recordings.

### Supply Chain And Release Drift

Threat: a public ZIP could contain stale files, development artifacts, missing
license notices, or a different source commit than expected.

Mitigations:

- `corepack pnpm run validate:release` performs frozen install, typecheck,
  build, tests, secret scan, license notice validation, package inspection, and
  checksum verification;
- the ZIP includes `RELEASE_MANIFEST.json` with version, backend version,
  artifact name, source commit, dirty state, and timestamp;
- strict release mode requires a clean tree and matching `vX.Y.Z` tag.

## Out Of Scope

- Protecting arbitrary local sound files from users who already control the
  same Steam Deck account.
- Protecting against a compromised Decky Loader installation.
- Guaranteeing compatibility across unvalidated SteamOS or Decky Loader
  versions.
- Remote control, telemetry, cloud sync, and network playback. These are
  non-goals unless a future design review explicitly changes the model.

## Release Review Checklist

Before public release, confirm:

- no LAN listener or telemetry path was added;
- optional device-access diagnostic results are recorded;
- privileged file writes still reject symlinks and audio subprocesses still
  drop to the Steam user;
- symlink escape tests still pass;
- subprocess calls use argument lists where practical;
- support docs still require redaction for logs;
- `docs/THIRD_PARTY_NOTICES.md` and `docs/THIRD_PARTY_LICENSES.md` match
  production dependencies, source imports, direct development dependencies,
  and icon attribution;
- strict tagged release validation passes from a clean checkout.
