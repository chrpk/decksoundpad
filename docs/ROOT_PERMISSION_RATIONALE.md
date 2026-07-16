# Privilege and Device Access

DeckSoundpad does not request Decky's `root` flag. `plugin.json` intentionally
uses an empty `flags` array, so installation and startup never ask Decky to
elevate the plugin.

The panel, bridge, library scanning, audio repair, playback, and overlay IPC
run as the normal Decky/Steam user. The plugin also does not modify the SteamOS
root filesystem, install packages, expose a LAN API, or invoke `sudo`,
`pkexec`, or another elevation helper.

## Optional device monitoring

The backend can inspect `/dev/input/event*` and `/dev/hidraw*` for L5/R5 and
overlay controls. These paths are opportunistic: they are disabled when the
process is not root or the device cannot be opened, and enabling
`DECKSOUNDPAD_ENABLE_INPUT_HOTKEY=1` does not grant permissions. Users who need
these optional hotkeys must grant the normal Steam user access through their
system/device configuration; the plugin never requests that access itself.

Overlay input grabbing with `EVIOCGRAB` follows the same rule and is skipped
when device access is unavailable. All other plugin workflows remain usable
without device monitoring.

## Release rule

Release validation must keep `flags` free of `root`. Hardware checks should
record whether optional input monitoring works under the target SteamOS device
permissions, but a failure is not a reason to add privilege escalation back to
the plugin. Documentation and release notes should describe device access as
optional and user-configured.
