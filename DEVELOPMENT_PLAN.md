# DeckSoundpad Development Plan

Date: 2026-06-12

## Mission

Build a Decky Loader soundboard for Steam Deck that runs in the background,
offers Decky and LAN web controls, and mixes soundboard audio plus the real mic
into a virtual source named `DeckSoundpad Mic`.

## MVP Constraints

- No root flag by default.
- No SteamOS root filesystem changes.
- No package installation through `pacman`.
- Use Decky environment directories when present.
- Default sound library: `~/Music/DeckSoundpad`.
- Only play indexed library sounds; never accept arbitrary playback paths.

## Phase Order

1. Repository bootstrap from the official Decky plugin template.
2. Config, path, logging, and security modules with tests.
3. Sound library scanner with tests.
4. Mocked PipeWire/PulseAudio command parsing and real mic detection tests.
5. Audio router using `pactl` modules with idempotent ensure/repair.
6. Player backend detection and process group tracking.
7. Daemon API with token auth and status/sounds/play/stop/audio/settings endpoints.
8. Thin Decky Python backend bridge.
9. Decky React panel.
10. Mobile web UI.
11. Sleep/resume repair and diagnostics.
12. Packaging ZIP.

## Definition Of Done

MVP is complete when a Steam Deck user can install the ZIP, add sounds under
`~/Music/DeckSoundpad`, repair/create the virtual mic, select
`DeckSoundpad Mic` in voice apps, play sounds from Decky or phone, survive
plugin reload without duplicate modules, and reset only DeckSoundpad-created
audio modules.
