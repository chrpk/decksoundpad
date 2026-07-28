# Hardware Validation Record

Copy this file into a release issue or release PR and fill it out for each
public release candidate tested on real Steam Deck hardware.

## Release Candidate

- Version:
- Commit:
- ZIP artifact:
- ZIP SHA-256:
- Tester:
- Date:

## Device And Runtime

- Steam Deck model:
- SteamOS version:
- Kernel version from `uname -a`:
- Decky Loader version:
- DeckSoundpad version shown at the top of the Decky panel:
- Install method:
- Game Mode or Desktop Mode:

## Required Commands

Run from Desktop Mode Konsole after pressing Repair audio routing:

```bash
pactl info
pactl list sources short
pactl list sinks short
pactl list modules short | grep -i decksoundpad
pactl get-default-source
ls -l ~/Public/DeckSoundpad/logs/
```

Attach or paste relevant redacted output. Logs may contain local usernames,
paths, and audio device names.
Use `docs/DIAGNOSTICS.md` for the full support-data checklist and redaction
rules.

## Audio Validation

- [ ] `DeckSoundpad mic` appears as `decksoundpad_mic`.
- [ ] Internal mix sink appears as `decksoundpad_sink`.
- [ ] Repair audio routing completes without backend error.
- [ ] WAV file plays into `DeckSoundpad mic`.
- [ ] MP3, OGG, or FLAC behavior is recorded.
- [ ] Real mic passthrough enabled: real mic and soundboard are both audible.
- [ ] Real mic passthrough disabled: soundboard-only mode works.
- [ ] At least one voice app detects `DeckSoundpad mic`.
- [ ] Voice app input meter moves when a sound plays.

Voice app tested:

Result notes:

## External Overlay Validation

- [ ] Game launched in Game Mode.
- [ ] `Automatic` retains the built-in Steam Deck HID/input behavior.
- [ ] A connected external controller appears in Controller input settings.
- [ ] Explicit controller selection persists after closing and reopening Decky.
- [ ] Only the explicitly selected controller toggles and navigates the overlay.
- [ ] Disconnecting the selected controller is shown as unavailable without
      silently falling back; choosing `Automatic` restores the fallback.
- [ ] L4, L5, R4, and R5 can each be selected under DeckSoundpad Settings.
- [ ] Each selected rear button toggles the overlay.
- [ ] Overlay appears over the game, not as a Decky modal.
- [ ] D-pad changes selection.
- [ ] L1/R1 changes page when enough sounds exist.
- [ ] A plays selected sound and hides overlay.
- [ ] Configured rear button closes overlay.
- [ ] `bridge.log` contains HID report and selected-button handling lines.
- [ ] `external-overlay.log` has no crash or display initialization error.

Game tested:

Result notes:

## No-Root Device Diagnostic

The release candidate already contains no `root` flag. Validate optional device
access as the normal Steam user and record unavailable paths as expected where
SteamOS permissions do not expose them.

- [ ] Decky panel loads without root.
- [ ] Library refresh works without root.
- [ ] Repair audio routing works without root.
- [ ] Sound playback works without root.
- [ ] `/dev/hidraw*` monitoring works with normal-user permissions, or is documented as unavailable.
- [ ] `/dev/input/event*` monitoring works with normal-user permissions, or is documented as unavailable.
- [ ] Configured rear-button and R5 previous-sound hotkeys work with normal-user permissions, or are documented as unavailable.
- [ ] External overlay starts without elevated privileges.
- [ ] Overlay input grab is skipped safely when device access is unavailable.

Conclusion:

- [ ] Confirm `plugin.json` contains no `root` flag.
- [ ] Confirm no code path invokes an elevation helper.
- [ ] Document any optional device permissions required by the target image.

Rationale:

## Screenshots And Demo Assets

Capture release assets that do not expose private data:

- [ ] Decky panel status view.
- [ ] Sound grid with safe sample names.
- [ ] Settings view.
- [ ] Voice app input selector showing `DeckSoundpad mic`.
- [ ] External overlay over a non-sensitive game or test scene.
- [ ] Optional short demo clip showing overlay navigation and playback.

Asset paths or release upload links:

Use `docs/RELEASE_ASSETS.md` for privacy, naming, and Decky Store image rules.

## Minimum Supported Versions

Use the lowest versions validated for this release candidate:

- Minimum SteamOS version:
- Minimum Decky Loader version:
- Notes on unsupported versions:

Do not publish a minimum supported version until at least one real device has
passed the audio and overlay checks above on that version.

After validation, update `docs/COMPATIBILITY.md` with the supported version
claim and known limitations for the release.
