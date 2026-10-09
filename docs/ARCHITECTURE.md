# Architecture

This document maps DeckSoundpad's modules and data flows for contributors and
release reviewers. It focuses on local files, device access, subprocesses,
audio routing, and release artifacts.

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

- `src/components/StatusCard.tsx`: audio/backend readiness, **Test sound**, and
  **Restart DeckSoundpad**.
- `src/components/ControlsPanel.tsx`: **Controls guide** button that opens a
  dialog listing the in-game overlay and Decky menu controls.
- `src/components/SoundGrid.tsx`: sound count, configured folders,
  **Refresh sounds**, and **Change sound folder**.
- `src/components/SettingsPanel.tsx`: overlay button, controller input, sound
  volume, real mic passthrough, and mic volume settings.
- `src/types.ts`: TypeScript types for bridge payloads.
- `src/utils/`: shared helpers for error messages (`errors.ts`), the
  backend-running check (`status.ts`), and delays (`timing.ts`).
- `src/buildInfo.ts`: package version and build timestamp shown in the Decky
  panel for diagnostics and hardware validation.

Frontend changes should preserve narrow Steam Deck panel layouts, controller
navigation, useful disabled states, and short UI copy.

## Backend Modules

- `backend/decksoundpad/audio_router.py`: PipeWire/PulseAudio route detection,
  module loading, repair, and cleanup.
- `backend/decksoundpad/audio_player.py`: playback backend selection and
  subprocess-based audio playback.
- `backend/decksoundpad/audio_formats.py`: file extensions the player supports,
  split into direct (`.wav`, `.flac`, `.ogg`) and transcoded (`.mp3`, `.m4a`,
  `.aac`) formats.
- `backend/decksoundpad/beep.py`: generates the **Test sound** beep as a 48 kHz
  stereo WAV file.
- `backend/decksoundpad/library.py`: local library scanning, path resolution,
  metadata, and symlink escape policy.
- `backend/decksoundpad/config.py`: persisted settings and defaults.
- `backend/decksoundpad/models.py`: dataclasses for sound items, PulseAudio
  sources and modules, and the status payloads returned to the UI.
- `backend/decksoundpad/paths.py`: settings, runtime, log, and public log paths
  from Decky's environment variables, with home-directory fallbacks.
- `backend/decksoundpad/safe_files.py`: creates directories, opens regular
  files, and sets Unix socket owner and mode without following symlinks.
- `backend/decksoundpad/external_overlay.py`: GTK/X11 external overlay process
  that draws the sound grid and the post-play toast.
- `backend/decksoundpad/overlay_layout.py`: overlay grid geometry and touch hit
  testing, free of GTK so tests can import it.
- `backend/decksoundpad/overlay_model.py`: overlay tabs (Recent and one per
  sound folder), cursor and page movement, stored Recent sounds, and the mic
  status shown in the overlay header.
- `backend/decksoundpad/input_devices.py`: evdev/hidraw constants, controller
  discovery, Steam Deck HID report parsing, and key-press classification used
  by the bridge's hotkey and overlay input monitors.
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
4. While the Quick Access menu is open, the UI polls status and displays
   current backend/audio readiness.

### Library Scanning

1. Configured library directories default to `~/Music/DeckSoundpad`.
2. `library.py` resolves local files and ignores symlinks that escape
   configured roots unless the user explicitly opts in.
3. Only local metadata needed for display/playback is cached.
4. Sound files are not uploaded or copied into the plugin package.

### Playback And Audio Routing

1. The user plays a sound from the external overlay, or presses **Test sound**
   in the Decky panel to play the generated beep.
2. `app.py` ensures the audio route exists before playback when required.
3. `audio_router.py` manages the `DeckSoundpad mic` virtual route through local
   PipeWire/PulseAudio tooling.
4. `audio_player.py` first tries its low-latency `pacat` mixer, then falls back
   to an available playback backend such as `pw-play`, `ffmpeg`, or `mpv`.
5. Output is mixed into the virtual microphone route.

### External Overlay

1. `main.py` discovers compatible Linux evdev controllers (through
   `input_devices.py`) and watches the selected input. `Automatic` retains
   Steam Deck HID plus compatible evdev monitoring; an explicit controller
   uses only its normalized evdev events.
2. The rear button selected in Decky settings (L4, L5, R4, or R5; L5 by
   default) toggles the overlay.
3. While an explicit controller is selected, its grabbed evdev stream handles
   A, B, X, Y, D-pad, L1/R1, and the configured rear button while the overlay
   is visible. R5 replays the most recent sound unless it is the overlay
   button.
4. `main.py` starts `external_overlay.py` as the Steam session user when
   possible.
5. Local Unix sockets carry overlay traffic: `main.py` sends overlay state to
   `external-overlay.sock`, and the overlay sends touch selections back to
   `external-overlay-actions.sock`, which `main.py` owns. No Decky callable
   controls the overlay.
6. Overlay commands are limited to selection, paging, tab selection,
   playback, stopping playback, and close.
7. Pure helpers keep the overlay testable without a display:
   `overlay_model.py` builds the Recent and folder tabs and moves the cursor,
   and `overlay_layout.py` holds the grid geometry and touch hit testing that
   the GTK renderer uses.

## Local Files And Logs

DeckSoundpad can read or write:

- configured sound library directories;
- Decky-managed plugin settings;
- runtime state in the plugin runtime directory (`audio_modules.json`,
  `library_cache.json`, and the **Test sound** file `test_beep.wav`);
- overlay Unix sockets under `/run/user/<uid>/decksoundpad/`, or under the
  plugin runtime directory when `/run/user/<uid>` does not exist;
- local PipeWire/PulseAudio state;
- local input devices for overlay/hotkey behavior;
- logs under the plugin log directory;
- mirrored support logs under `~/Public/DeckSoundpad/logs/`.

Public support docs require users to redact usernames, home paths, device names,
private sound names, account details, and credentials before sharing logs.

## Privileges And Device Access

`plugin.json` declares an empty `flags` array and never requests Decky's root
mode. Local input and overlay integration are opportunistic: the `/dev/input`
and `/dev/hidraw` readers start for every user and skip devices the normal
Steam user cannot open. See `docs/ROOT_PERMISSION_RATIONALE.md` for the
no-root model.

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
