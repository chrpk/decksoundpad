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
- DeckSoundpad version shown at the bottom of the Decky panel:
- Install method:
- Game Mode or Desktop Mode:

## Required Commands

Run from Desktop Mode Konsole after pressing Restart DeckSoundpad:

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
- [ ] Restart DeckSoundpad completes without backend error.
- [ ] WAV file plays into `DeckSoundpad mic`.
- [ ] MP3, OGG, or FLAC behavior is recorded.
- [ ] Real mic passthrough enabled: real mic and soundboard are both audible.
- [ ] Real mic passthrough disabled: soundboard-only mode works.
- [ ] Sound volume at 150% is louder than at 100% in the voice app.
- [ ] Mic volume at 150% makes the real mic louder in `DeckSoundpad mic` only;
      the Steam input level is unchanged (`pactl list sink-inputs` shows the
      loopback stream at 150%).
- [ ] Mic volume description names the input device selected in Steam
      Settings > Audio.
- [ ] At least one voice app detects `DeckSoundpad mic`.
- [ ] Voice app input meter moves when a sound plays.
- [ ] After sleep/resume, a played sound reaches `DeckSoundpad mic` again
      without Restart DeckSoundpad (record whether the first sound is lost).

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
- [ ] D-pad changes selection and flows onto the next page past the last row.
- [ ] L1/R1 changes page, and crosses into the next tab (Recent or a sound
      folder) at either end.
- [ ] A plays selected sound and hides overlay.
- [ ] After A, a toast naming the sound shows near the bottom for about two
      seconds, and the game keeps receiving controller and touch input.
- [ ] X plays the selected sound and keeps the overlay open; the tile shows a
      playing marker until the sound ends.
- [ ] Y stops all playing sounds.
- [ ] B and the configured rear button close the overlay without playing.
- [ ] R5 replays the most recent sound with the overlay closed (when R5 is not
      the overlay button).
- [ ] Tapping a tile plays it, tapping a tab switches to it, and tapping
      outside the grid closes the overlay.
- [ ] Header mic status matches the Decky status card.
- [ ] A sound with a Japanese or Cyrillic name renders as text, not boxes.
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
- [ ] Restart DeckSoundpad works without root.
- [ ] Sound playback works without root.
- [ ] `/dev/hidraw*` monitoring works with normal-user permissions, or is documented as unavailable.
- [ ] `/dev/input/event*` monitoring works with normal-user permissions, or is documented as unavailable.
- [ ] Configured rear-button and R5 replay hotkeys work with normal-user permissions, or are documented as unavailable.
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

Before publishing, remove usernames, home-directory paths, account names,
invite links, and chat content. A Decky Store submission also needs
`plugin.json` `publish.image` set to an HTTPS PNG URL.

## Minimum Supported Versions

Use the lowest versions validated for this release candidate:

- Minimum SteamOS version:
- Minimum Decky Loader version:
- Notes on unsupported versions:

Do not publish a minimum supported version until at least one real device has
passed the audio and overlay checks above on that version.

After validation, update `docs/COMPATIBILITY.md` with the supported version
claim and known limitations for the release.
