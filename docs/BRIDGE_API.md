# Decky Bridge API

This document is the public contract between the React frontend and the Python
Decky plugin bridge. It exists so contributors can review callable changes
without reverse-engineering both runtimes.

## Scope

The bridge is local and in-process through Decky Loader's `callable` API:

- frontend wrapper: `src/api/decky.ts`;
- TypeScript payload types: `src/types.ts`;
- Python callable implementation: `main.py`;
- backend facade called by the bridge: `backend/decksoundpad/app.py`;
- behavior tests: `backend/tests/test_main_bridge.py`.

DeckSoundpad does not expose these methods over HTTP, WebSocket, LAN, or a
remote control API. Adding a network-exposed API requires a separate design
review plus updates to `docs/THREAT_MODEL.md`, `docs/PRIVACY.md`, and
`docs/ARCHITECTURE.md`.

## Callable Methods

The frontend must call only the Python methods listed here.

| Frontend wrapper | Decky method | Arguments | Success response | Timeout |
| --- | --- | --- | --- | --- |
| `getStatus()` | `get_status` | none | `DeckSoundpadStatus` | 900 ms |
| `startBackend()` | `start_backend` | none | `DeckSoundpadStatus` | 1200 ms |
| `refreshLibrary()` | `refresh_library` | none | `LibraryRefreshResponse` | 2200 ms |
| `setLibraryFolder(folder)` | `set_library_folder` | absolute folder path | `LibraryFolderResponse` | 4000 ms |
| `playTestSound()` | `play_test_sound` | none | `PlaybackResponse` | 3000 ms |
| `restartDeckSoundpadAndWait()` | `repair_audio`, then `get_status` polling | none | `DeckSoundpadStatus` | 1500 ms per restart call, 20000 ms overall wait |
| `getSettings()` | `get_settings` | none | `Settings` | 1400 ms |
| `getInputDevices()` | `get_input_devices` | none | `InputDevicesResponse` | 1800 ms |
| `updateSettings(patch)` | `update_settings` | `Partial<Settings>` | `Settings` | 1600 ms |

`restartDeckSoundpadAndWait()` is a frontend helper, not a Python method. It calls
`repair_audio`, reports the immediate status to the caller, then polls
`get_status` every 500 ms until `restart_completed_id` reaches the
`restart_id` returned by that exact request and `restart_running` is false.
The audio-state check is retained only as compatibility behavior for an older
backend that does not return restart operation identifiers.

`play_sound` is not a public frontend bridge callable in the current UI. The
backend has `DeckSoundpadApp.play_sound()` and `main.py` uses it internally for
external overlay/hotkey playback. A future public frontend playback callable
must be added to this document, `src/api/decky.ts`, `src/types.ts`, and
`backend/tests/test_main_bridge.py` in the same change.

## Status Response

`DeckSoundpadStatus` is returned by `get_status`, `start_backend`, and
`repair_audio` through the frontend helper.

```ts
interface DeckSoundpadStatus {
  version?: string;
  backend_running: boolean;
  restart_running?: boolean;
  restart_id?: number;
  restart_completed_id?: number;
  audio: AudioStatus;
  player: { backend: string | null };
  library: { count: number; dirs?: string[] };
  mic_passthrough_enabled?: boolean;
  playback_route?: PlaybackRoute;
}
```

While a restart is active, `get_status` always reports `audio.state` as
`repairing`, even if an older route check finishes and attempts to publish a
cached `ready` result. Restart IDs are monotonically increasing within one
backend process and prevent an unrelated terminal status from ending frontend
polling early.

`AudioStatus` mirrors `backend/decksoundpad/models.py`:

```ts
interface AudioStatus {
  pipewire_available: boolean;
  pactl_available: boolean;
  sink_exists: boolean;
  virtual_mic_exists: boolean;
  loopback_exists: boolean;
  selected_real_mic: string | null;
  selected_real_mic_description: string | null;
  default_source: string | null;
  is_default_source: boolean;
  last_error: string | null;
  state?: string;
}
```

`playback_route` is diagnostic route metadata:

```ts
interface PlaybackRoute {
  backend: string | null;
  virtual_input: "decksoundpad_mic";
  sink: "decksoundpad_sink";
  mode: "stream_to_internal_sink" | "offline";
}
```

The normal backend route mode is `stream_to_internal_sink`. Bridge fallbacks use
`offline` when backend status cannot be read.

## Library Refresh Response

`refresh_library` rescans configured local library directories and returns:

```ts
interface LibraryRefreshResponse {
  ok: boolean;
  error?: string;
  sounds: SoundItem[];
}

interface SoundItem {
  id: string;
  display_name: string;
  path: string;
  relative_path: string;
  category: string;
  extension: string;
}
```

On backend failure the bridge returns:

```json
{ "ok": false, "error": "backend unavailable", "sounds": [] }
```

Sound paths are local file paths. Public issues and logs must redact private
home paths and private sound names before sharing.
Library roots must be real directories owned by the Steam user. The backend
rejects symlink roots and non-user-owned sound files while running as the
normal Decky/Steam user.

`library.dirs` in the status response lists the configured library folders as
absolute paths (with `~` expanded) so the frontend can open Decky's folder
picker at the current folder.

## Library Folder Response

`set_library_folder` replaces `library_dirs` with the chosen folder, rescans it,
and persists the setting only if the scan succeeds:

```ts
interface LibraryFolderResponse {
  ok: boolean;
  error?: string;
  settings: Settings;
  sounds: SoundItem[];
}
```

A relative path, a path that is not a directory, a symlink root, or a
folder not owned by the Steam user returns `ok: false` with the error, the
unchanged settings, and an empty `sounds` array. The previous library stays
active. On backend failure the bridge returns the same shape with
`error: "backend unavailable"` and the last loaded settings.

## Test Sound Response

`play_test_sound` writes a short beep to `test_beep.wav` in the plugin runtime
directory and plays it through the same route as library sounds:

```ts
interface PlaybackResponse {
  ok: boolean;
  error?: string;
}
```

On success the backend also returns `playback_id`, `sound_id`, `backend`, and
`route`, which the frontend type does not declare. On backend failure the
bridge returns `{ "ok": false, "error": "backend unavailable" }`.

## Input Device Response

`get_input_devices` discovers compatible Linux evdev controller nodes. The
response always begins with the `auto` option and then contains currently
readable controllers:

```ts
interface InputDevicesResponse {
  devices: Array<{
    id: "auto" | `evdev:${string}`;
    name: string;
    path: string;
    label: string;
  }>;
}
```

Persisted `evdev:` IDs are derived from the kernel-reported name, physical
location, and unique ID, never from a raw `/dev/input/eventN` number. Nodes
without a physical location or unique ID may still participate in `Automatic`
mode, but are not offered for explicit persistence. Discovery also requires
controller navigation plus supported rear-button capabilities before a node can
be monitored or grabbed. An unavailable configured device remains selected in
the UI until the user chooses another device or `Automatic`.

## Settings Response

`get_settings` returns the full backend settings payload. `update_settings`
accepts a partial patch with the same keys and returns the full validated
settings payload after persistence.

```ts
interface Settings {
  library_dirs: string[];
  master_volume: number;
  overlap_mode: "overlap" | "single" | "per_sound";
  max_concurrent_sounds: number;
  max_playback_seconds: number;
  selected_mic_source: string | null;
  mic_passthrough_enabled: boolean;
  mic_passthrough_volume: number;
  auto_repair_on_resume: boolean;
  background_healthcheck_enabled: boolean;
  overlay_hotkey_button: "l4" | "l5" | "r4" | "r5";
  overlay_input_device: "auto" | `evdev:${string}`;
  allowed_extensions: string[];
  allow_symlinks_outside_libraries: boolean;
}
```

`master_volume` and `mic_passthrough_volume` are linear gains from `0.0` to
`1.5` (150%). Changing `mic_passthrough_volume` sets the volume of the running
passthrough loopback stream; the real mic's own level is left alone.

Validation lives in `backend/decksoundpad/config.py`. Unknown keys fail backend
validation and the bridge returns the previous settings fallback. A patch that
touches `library_dirs`, `allowed_extensions`, or
`allow_symlinks_outside_libraries` rescans the library before it is saved. New settings
must be added to the backend dataclass, validation, defaults, `src/types.ts`,
and relevant UI/tests together.

## Startup And Repair Semantics

`start_backend` must return quickly. It starts backend initialization in a
background thread, then returns `get_status`. The background startup performs
audio repair and library refresh once per plugin load.

`repair_audio` is retained as the callable name for compatibility, but now starts
an asynchronous full runtime restart. It stops playback and the persistent
mixer, input listeners, the overlay action server, and the external overlay;
releases input grabs; tears down the audio graph; reloads settings; recreates the
router/player/library components; rediscovers controller devices; restarts the
bridge workers; rebuilds the route; and rescans sounds. It can supersede an
in-flight route check; stale route-check status cannot overwrite restart
progress. The Python method returns immediately and the frontend polls until the
task settles.

## Error And Fallback Semantics

`main.py` wraps backend calls with `_call_backend`. Exceptions are recorded in
Decky/backend logs and mirrored support logs when available. The frontend
should treat bridge timeouts, `ok: false`, and `backend_running: false` as
recoverable user-visible states rather than crashes.

Fallbacks are intentionally shaped like the success payloads:

- `get_status` returns `backend_running: false`, audio `state: "offline"`, and
  `audio.last_error: "backend unavailable"`;
- `refresh_library` returns `ok: false`, an error string, and an empty
  `sounds` array;
- `get_settings` and `update_settings` return the last loaded settings.

## Logging And Privacy

Bridge logs summarize these actions: `sounds_refresh`, `audio_repair`, and
`settings_update`. Logging must stay bounded and avoid full unredacted file
paths where a count, key list, or small sample is enough. Public support
requests must follow `docs/DIAGNOSTICS.md` redaction rules.

## Change Checklist

Any change that adds, removes, renames, or reshapes a bridge callable must
update all of these in the same pull request:

- `src/api/decky.ts`;
- `src/types.ts`;
- `main.py`;
- `backend/decksoundpad/app.py`, when backend facade behavior changes;
- `backend/tests/test_main_bridge.py`;
- this document;
- `docs/ARCHITECTURE.md` and `docs/THREAT_MODEL.md` if trust boundaries,
  logging, local files, subprocesses, sockets, or root behavior change.

Run these before opening the change:

```bash
corepack pnpm run typecheck
corepack pnpm run test
corepack pnpm run validate:repo
corepack pnpm run validate:release
```
