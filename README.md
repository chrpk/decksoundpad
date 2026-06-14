# DeckSoundpad

Steam Deck soundboard controlled from Decky UI or a phone browser. It mixes
soundboard playback with your real microphone into a single virtual input named
`DeckSoundpad mic`.

## Requirements

- Steam Deck / SteamOS
- Decky Loader
- PipeWire/PulseAudio compatibility tools available on the system

No root filesystem modification or `pacman` package installation is required.

## Install

Build the plugin ZIP and install it through Decky developer tools:

```bash
corepack enable
corepack pnpm i
corepack pnpm run build
scripts/package_plugin.sh
```

## Add Sounds

Put files in:

```text
~/Music/DeckSoundpad
```

Supported target extensions for MVP are WAV, FLAC, OGG, and MP3. Actual
playback support depends on local availability of `pw-play`, `ffmpeg`, or
`mpv`.

The plugin ZIP includes bundled MP3 assets under `assets/`. DeckSoundpad indexes
those bundled files directly, so no sample download is required and no sample
copy is written into your music folder.

## Use

1. Open the Decky panel.
2. Select Repair audio routing.
3. Select `DeckSoundpad mic` in Discord, Steam Voice, a game, or browser voice chat.
4. Press sound buttons from Decky or open the local web UI URL for phone control.

## Troubleshooting

- No mic detected: sounds can still play into `DeckSoundpad mic`, but Steam Deck mic passthrough is unavailable.
- Sound plays but not in Discord: select `DeckSoundpad mic` as Discord's input device.
- MP3 not supported: install/use a backend with MP3 support, such as `ffmpeg` or `mpv`, when available.
- Web UI unreachable: confirm the phone is on the same LAN and use the URL from Decky.
- Sleep/resume breaks audio: press Repair to rebuild the PipeWire/PulseAudio graph.
- Logs on Steam Deck are mirrored to `~/Public/DeckSoundpad/logs/`:
  `bridge.log` for Decky bridge errors, `daemon.log` for backend logs, and
  `daemon-stdio.log` for daemon stdout/stderr during startup.

## Steam Deck Audio PoC

Before testing the Decky UI, validate the audio graph directly from Desktop Mode
Konsole:

```bash
scripts/poc_steamdeck_audio.sh
```

Verify that the virtual input exists:

```bash
pactl list sources short | grep decksoundpad
```

Cleanup:

```bash
scripts/poc_reset_audio.sh
```

See [docs/STEAMDECK_AUDIO_POC.md](docs/STEAMDECK_AUDIO_POC.md) for pass/fail
criteria and options.

## Security

The web UI is intended for local LAN use without authentication. Do not expose
the configured port to the internet.

## Development

```bash
corepack enable
corepack pnpm i
corepack pnpm run build
python3 -m unittest discover backend/tests
scripts/dev_audio_probe.sh
```

### macOS Simulation

Use simulation mode to test the daemon, REST API, web UI, bundled sample
library, and Decky-facing behavior on macOS without PipeWire, `pactl`,
`pw-play`, or Steam Deck audio devices.

```bash
scripts/dev_simulate_macos.sh
```

Then open the URL printed by the script. If the requested port is already busy,
the daemon auto-selects another local port and writes it to:

```text
.tmp-run/macos-sim/runtime/session.json
```

Quick smoke test:

```bash
scripts/dev_simulation_smoke.sh
```

The script uses `.tmp-run/macos-sim` for settings/runtime/log files and disables
web auth for `127.0.0.1` simulation only.

Simulation is enabled by:

```bash
DECKSOUNDPAD_SIMULATE=1
```

In this mode playback is recorded by an in-memory simulated player and status
reports a simulated `DeckSoundpad mic` route. Production Deck audio routing is
unchanged when the env var is not set.

## License

MIT
