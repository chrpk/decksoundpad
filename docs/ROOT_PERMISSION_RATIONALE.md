# Root Permission Rationale

DeckSoundpad currently requests the Decky `root` flag in `plugin.json`.
Deckbrew documents this flag as something to use only when actually required,
so every public release must re-check whether it is still necessary.

## Privileged Code Paths

The current implementation uses privileged access for these local-only features:

- L5/R5 direct input monitoring:
  - `_start_hotkey_monitor()` and `_start_hidraw_monitor()` call
    `_input_hotkey_monitor_enabled()`.
  - The default path requires `os.geteuid() == 0`.
  - The code reads `/dev/input/event*` and `/dev/hidraw*`.
- External overlay gamepad capture:
  - `_grab_external_overlay_input_devices()` opens `/dev/input/event*`.
  - It calls `EVIOCGRAB` so gamepad input can be routed to the overlay while
    the overlay is visible.
- Overlay process ownership:
  - The backend prepares runtime directories, logs, and Unix sockets while
    running as Decky.
  - When root is available, it can chown those resources to the Steam Deck user
    and launches the GTK overlay with Python's UID, GID, and supplementary-group
    subprocess controls.

Privileged file handling is intentionally narrow: configuration, state, cache,
and log files are opened without following symlinks, directory and socket
metadata changes are no-follow operations, and audio-routing/playback child
processes drop to the Steam user's UID, GID, and supplementary groups.

## Non-Privileged Behavior

The Decky panel, backend bridge, sound library scanning, settings, and audio
repair/playback paths should remain local and in-process. The project does not
ship a LAN HTTP API and should not require SteamOS root filesystem changes.

If the plugin is run without root:

- direct `/dev/input` and `/dev/hidraw` monitoring is disabled by default;
- the Decky panel should remain usable;
- users can explicitly opt into input monitoring with
  `DECKSOUNDPAD_ENABLE_INPUT_HOTKEY=1` for diagnostics, but that does not grant
  permissions by itself.

## Release Validation

Before a public release can claim the `root` flag is required, test both modes
on real Steam Deck hardware:

1. Build and install a release candidate with `flags: ["root"]`.
2. Complete `docs/STEAMDECK_AUDIO_POC.md`.
3. Complete `docs/EXTERNAL_OVERLAY_POC.md`.
4. Build and install a diagnostic candidate without the `root` flag.
5. Record which features still work from the Decky panel.
6. Record whether `/dev/input`, `/dev/hidraw`, L5/R5 hotkeys, overlay
   navigation, and overlay input grab fail without root.
7. If all required workflows work without root, remove the flag before release.
8. If only optional workflows need root, consider splitting them behind an
   explicit opt-in or feature flag.

The release notes should summarize the result instead of merely saying root is
needed.
