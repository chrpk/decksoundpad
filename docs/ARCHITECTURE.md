# Architecture

This document maps the runtime shape of DeckSoundpad for contributors and
release reviewers. It is intentionally focused on public-maintenance risk:
local files, privileged behavior, subprocesses, audio routing, and release
artifacts.

## Runtime Shape

DeckSoundpad is a local Decky Loader plugin with two primary parts:

- TypeScript/React Decky UI bundled to `dist/index.js`.
- Python backend loaded by Decky through `main.py` and
  `backend/decksoundpad/`.

Decky calls backend methods in-process through the plugin bridge. The project
must not add a LAN HTTP API, telemetry endpoint, remote asset loader, or network
control path without a separate design review, threat-model update, and privacy
documentation update.

## Entry Points

- `src/index.tsx`: Decky panel entry point. It renders status, settings,
  controls, sound grid, repair actions, and visible build metadata.
- `src/api/decky.ts`: typed frontend calls into Decky/backend methods.
- `src/state/store.ts`: frontend polling and state loading.
- `main.py`: Decky Python plugin bridge. It exposes callable methods, starts
  backend services, mirrors support logs, handles hotkeys, and coordinates the
  external overlay process.
- `backend/decksoundpad/app.py`: backend application facade for status, library,
  playback, settings, and audio route repair.

The stable frontend-to-bridge callable contract is documented in
`docs/BRIDGE_API.md`. Changes to callable names, payloads, return shapes,
timeouts, or fallbacks must update the TypeScript wrapper, Python bridge,
bridge tests, and that document together.

## Frontend Modules

- `src/components/StatusCard.tsx`: audio/backend readiness and repair action UI.
- `src/components/ControlsPanel.tsx`: in-game and Decky control reference.
- `src/components/SoundGrid.tsx`: sound library summary and refresh action.
- `src/components/SettingsPanel.tsx`: real-microphone passthrough setting.
- `src/buildInfo.ts`: package version and build timestamp shown in the Decky
  panel for diagnostics and hardware validation.

Frontend changes should preserve narrow Steam Deck panel layouts, controller
navigation, useful disabled states, and short UI copy.

## Backend Modules

- `backend/decksoundpad/audio_router.py`: PipeWire/PulseAudio route detection,
  module loading, repair, and cleanup.
- `backend/decksoundpad/audio_player.py`: playback backend selection and
  subprocess-based audio playback.
- `backend/decksoundpad/library.py`: local library scanning, path resolution,
  metadata, and symlink escape policy.
- `backend/decksoundpad/config.py`: persisted settings and defaults.
- `backend/decksoundpad/external_overlay.py`: GTK/X11 external overlay process.
- `backend/decksoundpad/simulation.py`: non-SteamOS simulation for tests and
  contributor development.
- `backend/decksoundpad/process.py`: subprocess helpers.
- `backend/decksoundpad/logging_setup.py`: backend log configuration.

Backend changes should prefer argument-list subprocess calls, reject path
escapes by default, avoid permanent SteamOS root filesystem writes, and keep
public logs free of unnecessary sensitive data.

## Main Data Flows

### Status And Settings

1. The Decky UI calls bridge methods through `src/api/decky.ts`.
2. `main.py` dispatches calls to the backend application.
3. `backend/decksoundpad/app.py` combines config, library, player, and audio
   route state.
4. The UI polls status and displays current backend/audio readiness.

### Library Scanning

1. Configured library directories default to `~/Music/DeckSoundpad`.
2. `library.py` resolves local files and ignores symlinks that escape
   configured roots unless the user explicitly opts in.
3. Only local metadata needed for display/playback is cached.
4. Sound files are not uploaded or copied into the plugin package.

### Playback And Audio Routing

1. The user plays a sound from the external overlay.
2. `app.py` ensures the audio route exists before playback when required.
3. `audio_router.py` manages the `DeckSoundpad mic` virtual route through local
   PipeWire/PulseAudio tooling.
4. `audio_player.py` chooses an available playback backend such as `pw-play`,
   `ffmpeg`, or `mpv`.
5. Output is mixed into the virtual microphone route.

### External Overlay

1. `main.py` discovers compatible Linux evdev controllers and watches the
   selected input. `Automatic` retains Steam Deck HID plus compatible evdev
   monitoring; an explicit controller uses only its normalized evdev events.
2. The rear button selected in Decky settings (L4, L5, R4, or R5; L5 by
   default) toggles the overlay.
3. While an explicit controller is selected, its grabbed evdev stream handles
   A, D-pad, L1/R1, and the configured rear button while the overlay is visible.
4. `main.py` starts `external_overlay.py` as the Steam session user when
   possible.
5. Backend-owned local sockets and bridge calls carry overlay actions.
6. Overlay commands are limited to selection, paging, playback, and close.

## Local Files And Logs

DeckSoundpad can read or write:

- configured sound library directories;
- Decky-managed plugin settings;
- local PipeWire/PulseAudio state;
- local input devices for overlay/hotkey behavior;
- logs under the plugin log directory;
- mirrored support logs under `~/Public/DeckSoundpad/logs/`.

Public support docs require users to redact usernames, home paths, device names,
private sound names, account details, and credentials before sharing logs.

## Privileged Behavior

`plugin.json` declares an empty `flags` array and never requests Decky's root
mode. Local input and overlay integration are opportunistic: `/dev/input` and
`/dev/hidraw` access is attempted only when the normal Steam user already has
permission. See `docs/ROOT_PERMISSION_RATIONALE.md` for the no-root model.

## Simulation And Tests

Simulation mode is enabled with:

```bash
DECKSOUNDPAD_SIMULATE=1
```

Simulation is useful for backend tests and non-SteamOS development, but it does
not prove Steam Deck compatibility. Hardware-sensitive behavior still requires
real Steam Deck validation using `docs/HARDWARE_VALIDATION.md`.

## Build And Release Artifacts

- `rollup.config.js` builds the frontend and injects package version/build time.
- `scripts/package_plugin.sh` stages the runtime plugin ZIP.
- `scripts/validate_release.sh` performs frozen install, typecheck, build,
  tests, local secret scan, license checks, ZIP inspection, manifest checks, and
  checksum verification.
- `RELEASE_MANIFEST.json` records package/backend version, API version, flags,
  artifact name, source commit, dirty state, and generation time.
- Runtime ZIPs must not include source files, tests, `.git`, `.github`, caches,
  dependency folders, logs, source maps, release media, or Python bytecode.

## Change Review Checklist

Before merging architecture-sensitive changes, check whether the change touches:

- subprocess command construction;
- path resolution, symlink handling, or library scanning;
- PipeWire/PulseAudio module loading or cleanup;
- input devices, HID reports, Unix sockets, or overlay actions;
- logs or public diagnostics;
- release packaging, manifests, checksums, workflows, or dependency notices;
- Decky callable names, payloads, return shapes, timeouts, or fallbacks;
- root-flag requirements or no-root behavior.

If it does, update the relevant tests, `docs/THREAT_MODEL.md`,
`docs/BRIDGE_API.md`, `docs/ROOT_PERMISSION_RATIONALE.md`, release validation,
or hardware validation records as appropriate.
