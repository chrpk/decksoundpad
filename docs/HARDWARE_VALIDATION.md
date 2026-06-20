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
- [ ] L5 toggles the overlay.
- [ ] Overlay appears over the game, not as a Decky modal.
- [ ] D-pad changes selection.
- [ ] L1/R1 changes page when enough sounds exist.
- [ ] A plays selected sound and hides overlay.
- [ ] L5 closes overlay.
- [ ] `bridge.log` contains HID report and L5 handling lines.
- [ ] `external-overlay.log` has no crash or display initialization error.

Game tested:

Result notes:

## Root Flag Diagnostic

Build a diagnostic candidate without `flags: ["root"]` in `plugin.json`, then
repeat the core flows.

- [ ] Decky panel loads without root.
- [ ] Library refresh works without root.
- [ ] Repair audio routing works without root.
- [ ] Sound playback works without root.
- [ ] `/dev/hidraw*` monitoring works without root.
- [ ] `/dev/input/event*` monitoring works without root.
- [ ] L5/R5 direct hotkeys work without root.
- [ ] External overlay starts without root.
- [ ] Overlay input grab works without root.

Conclusion:

- [ ] Keep `root` flag for this release.
- [ ] Remove `root` flag before release.
- [ ] Split privileged features behind an explicit opt-in before release.

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
