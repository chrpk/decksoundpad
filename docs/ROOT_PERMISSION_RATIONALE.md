# Privilege and Device Access

DeckSoundpad does not request Decky's `root` flag. `plugin.json` uses an empty
`flags` array, so installation and startup never ask Decky to elevate the
plugin.

The panel, bridge, library scanning, audio repair, playback, and overlay IPC
run as the normal Decky/Steam user. The plugin also does not modify the SteamOS
root filesystem, install packages, expose a LAN API, or invoke `sudo`,
`pkexec`, or another elevation helper.

## Optional device monitoring

The backend can inspect `/dev/input/event*` and `/dev/hidraw*` for the
configured L4/L5/R4/R5 overlay hotkey, R5 replay shortcut, and overlay
controls. Decky runs the plugin as the normal Steam user, so these paths are
opportunistic: the readers start for every user and skip devices they cannot
open. Users who need these optional hotkeys must grant the normal Steam
user access through their system/device configuration; the plugin never
requests that access itself. Set `DECKSOUNDPAD_ENABLE_INPUT_HOTKEY=0` to disable
the readers.

Overlay input grabbing with `EVIOCGRAB` follows the same rule and is skipped
when device access is unavailable. All other plugin workflows remain usable
without device monitoring.

## Release rule

Release validation must keep `flags` free of `root`. Hardware checks should
record whether optional input monitoring works under the target SteamOS device
permissions, but a failure is not a reason to add privilege escalation back to
the plugin. Documentation and release notes should describe device access as
optional and user-configured.
