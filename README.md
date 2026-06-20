# DeckSoundpad

Steam Deck soundboard controlled from Decky UI. It mixes soundboard playback
with your real microphone into a single virtual input named `DeckSoundpad mic`.

## Status

DeckSoundpad is being prepared for public open-source release. The core plugin
is usable, but release candidates should pass the checks in
[docs/OPEN_SOURCE_READINESS.md](docs/OPEN_SOURCE_READINESS.md) before being
announced or submitted to a plugin index.

## Features

- Decky panel controls for library refresh, playback, audio repair, and settings.
- PipeWire/PulseAudio route that exposes soundboard output as `DeckSoundpad mic`.
- Optional real microphone passthrough into the same virtual input.
- Local sound library scanning from `~/Music/DeckSoundpad`.
- WAV, FLAC, OGG, and MP3 playback through available SteamOS audio tools.
- Steam Deck simulation mode for backend development on non-SteamOS machines.

## Requirements

- Steam Deck / SteamOS
- Decky Loader
- PipeWire/PulseAudio compatibility tools available on the system

No root filesystem modification or `pacman` package installation is required.
The Decky metadata requests the `root` flag because input monitoring and the
external overlay need privileged access to local device/socket resources. The
plugin does not expose a LAN API and does not modify the read-only SteamOS root
filesystem. See [docs/ROOT_PERMISSION_RATIONALE.md](docs/ROOT_PERMISSION_RATIONALE.md)
for the current rationale and release validation plan.
Compatibility status and minimum supported version evidence are tracked in
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Current Limitations

- Hardware validation is required before public release claims are final.
- SteamOS, Decky Loader, and PipeWire updates can change audio-routing behavior.
- Real microphone passthrough depends on the Deck's current input-device names.
- MP3 playback depends on locally available playback tools.
- The external overlay and L5 input path are the most hardware-sensitive parts.

## Build

Build the Decky frontend bundle:

Use Node 22 and pnpm 9.15.9. If you use nvm, run `nvm use` first to match the
repository's `.nvmrc`.

```bash
corepack enable
corepack pnpm i
corepack pnpm run build
```

Package the plugin ZIP:

```bash
corepack pnpm run package
```

The release artifacts are written to `out/DeckSoundpad-v<version>-full.zip` and
`out/DeckSoundpad-v<version>-full.zip.sha256`. Packaging requires either
`shasum` or `sha256sum` so the checksum is always produced.
This repository is not distributed through npm; `package.json` is marked
private to keep release distribution on the Decky/GitHub ZIP path.

GitHub also produces the same package from the `Tagged Release Artifact`
workflow. Push a matching `v<version>` tag, or run the workflow manually for an
existing tag, and it validates the package before attaching the ZIP and
checksum to the GitHub Release.

## Install From ZIP

1. Build the ZIP with `corepack pnpm run package`.
2. Copy the generated ZIP to the Steam Deck.
3. Install it through Decky Loader's plugin developer tools or extract it into
   Decky's plugin directory for local testing.
4. Restart Decky Loader if the plugin does not appear immediately.

Detailed install, update, rollback, and uninstall guidance is maintained in
[docs/INSTALLATION.md](docs/INSTALLATION.md).

## Add Sounds

Put files in:

```text
~/Music/DeckSoundpad
```

Supported target extensions are WAV, FLAC, OGG, and MP3. Actual playback
support depends on local availability of `pw-play`, `ffmpeg`, or `mpv`.

## Use

1. Open the Decky panel.
2. Select Repair audio routing.
3. Select `DeckSoundpad mic` in Discord, Steam Voice, a game, or browser voice chat.
4. Press L5 in-game to open the overlay and play sounds.

## Troubleshooting

- No mic detected: sounds can still play into `DeckSoundpad mic`, but Steam Deck mic passthrough is unavailable.
- Sound plays but not in Discord: select `DeckSoundpad mic` as Discord's input device.
- MP3 not supported: install/use a backend with MP3 support, such as `ffmpeg` or `mpv`, when available.
- Sleep/resume breaks audio: press Repair to rebuild the PipeWire/PulseAudio graph.
- Logs on Steam Deck are mirrored to `~/Public/DeckSoundpad/logs/`:
  `bridge.log` for Decky bridge errors and `backend.log` for backend logs.
- Logs may contain local usernames, paths, and audio device names. Redact them
  before posting public issues.

More cases are covered in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
Privacy and local data handling are documented in
[docs/PRIVACY.md](docs/PRIVACY.md).
Safe diagnostic collection is documented in
[docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md).

## Steam Deck Audio Check

Before testing voice chat, use the Decky panel's Repair audio routing action and
then verify that the virtual input exists from Desktop Mode Konsole:

Verify that the virtual input exists:

```bash
pactl list sources short | grep decksoundpad
```

See [docs/STEAMDECK_AUDIO_POC.md](docs/STEAMDECK_AUDIO_POC.md) for pass/fail
criteria.

## Security

DeckSoundpad no longer ships a standalone LAN web UI or HTTP API. Decky calls
the backend in-process.

Sound libraries are local filesystem paths. Symlinks that escape configured
library roots are ignored by default. See [SECURITY.md](SECURITY.md) for the
current security model and reporting process.

See [docs/PRIVACY.md](docs/PRIVACY.md) for local data and log-sharing
expectations.
The local threat model is documented in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Development

```bash
nvm use
corepack enable
corepack pnpm i
corepack pnpm run typecheck
corepack pnpm run build
python3 -m unittest discover backend/tests
```

Useful commands:

```bash
corepack pnpm run build
corepack pnpm run typecheck
corepack pnpm run test
corepack pnpm run check
corepack pnpm run scan:secrets
corepack pnpm run package
corepack pnpm run validate:release
corepack pnpm run validate:publication
```

### macOS Simulation

Use simulation mode to test the backend, bundled sample library, and Decky-facing
behavior on macOS without PipeWire, `pactl`, `pw-play`, or Steam Deck audio
devices.

Run tests or local Decky bridge calls with simulation enabled:

```bash
DECKSOUNDPAD_SIMULATE=1 python3 -m unittest discover backend/tests
```

Simulation is enabled by:

```bash
DECKSOUNDPAD_SIMULATE=1
```

In this mode playback is recorded by an in-memory simulated player and status
reports a simulated `DeckSoundpad mic` route. Production Deck audio routing is
unchanged when the env var is not set.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening larger changes. Public
release readiness is tracked in
[docs/OPEN_SOURCE_READINESS.md](docs/OPEN_SOURCE_READINESS.md).
Publication steps are tracked in
[docs/PUBLICATION_RUNBOOK.md](docs/PUBLICATION_RUNBOOK.md).
Architecture and module boundaries are documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The Decky callable contract is documented in
[docs/BRIDGE_API.md](docs/BRIDGE_API.md).
Reference repository comparisons are tracked in
[docs/REFERENCE_REPOS.md](docs/REFERENCE_REPOS.md).
Release notes should be drafted from
[docs/RELEASE_NOTES_TEMPLATE.md](docs/RELEASE_NOTES_TEMPLATE.md).
Support expectations are documented in [SUPPORT.md](SUPPORT.md).
Maintainer triage and release-owner expectations are documented in
[docs/MAINTAINER_GUIDE.md](docs/MAINTAINER_GUIDE.md).
Release screenshots, demo clips, and Decky Store media requirements are
documented in [docs/RELEASE_ASSETS.md](docs/RELEASE_ASSETS.md).
Install, update, rollback, and uninstall expectations are documented in
[docs/INSTALLATION.md](docs/INSTALLATION.md).

Third-party dependency and icon licenses are summarized in
[docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md), with bundled
license text in [docs/THIRD_PARTY_LICENSES.md](docs/THIRD_PARTY_LICENSES.md).

## License

MIT
