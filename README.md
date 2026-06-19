# DeckSoundpad

Steam Deck soundboard controlled from Decky UI. It mixes soundboard playback
with your real microphone into a single virtual input named `DeckSoundpad mic`.

## Requirements

- Steam Deck / SteamOS
- Decky Loader
- PipeWire/PulseAudio compatibility tools available on the system

No root filesystem modification or `pacman` package installation is required.

## Build

Build the Decky frontend bundle:

```bash
corepack enable
corepack pnpm i
corepack pnpm run build
```

The repository no longer tracks the old shell helpers under `scripts/`. Install
or package the built plugin through your current Decky developer workflow.

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
4. Press sound buttons from Decky.

## Troubleshooting

- No mic detected: sounds can still play into `DeckSoundpad mic`, but Steam Deck mic passthrough is unavailable.
- Sound plays but not in Discord: select `DeckSoundpad mic` as Discord's input device.
- MP3 not supported: install/use a backend with MP3 support, such as `ffmpeg` or `mpv`, when available.
- Sleep/resume breaks audio: press Repair to rebuild the PipeWire/PulseAudio graph.
- Logs on Steam Deck are mirrored to `~/Public/DeckSoundpad/logs/`:
  `bridge.log` for Decky bridge errors and `backend.log` for backend logs.

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

## Development

```bash
corepack enable
corepack pnpm i
corepack pnpm run build
python3 -m unittest discover backend/tests
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

## License

MIT
