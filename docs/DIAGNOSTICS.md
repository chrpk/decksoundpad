# Diagnostics

Use this guide when reporting a DeckSoundpad bug or validating a release
candidate. It collects enough local state to debug common audio, overlay, and
library problems without requiring private files or recordings.

## Before Collecting

1. Open the Decky panel.
2. Select DeckSoundpad.
3. Run Repair audio routing.
4. Reproduce the issue once.
5. Redact private data before posting anything publicly.

Do not attach private sound files, voice recordings, credentials, tokens, or
unredacted logs.

## Required Environment Details

Include:

- DeckSoundpad version shown at the top of the Decky panel, or the commit;
- install method;
- Steam Deck model;
- SteamOS version;
- Decky Loader version;
- Game Mode or Desktop Mode;
- target voice app or game, if relevant;
- whether `DeckSoundpad mic` was selected in the voice app.

## Audio Routing Commands

Run from Desktop Mode Konsole after Repair audio routing:

```bash
pactl info
pactl list sources short
pactl list sinks short
pactl list modules short | grep -i decksoundpad
pactl get-default-source
```

For public issues, paste only the relevant lines and redact device names that
identify personal hardware.

## Log Locations

DeckSoundpad mirrors support logs to:

```text
~/Public/DeckSoundpad/logs/bridge.log
~/Public/DeckSoundpad/logs/backend.log
~/Public/DeckSoundpad/logs/external-overlay.log
```

Before sharing logs, redact:

- local usernames and home-directory paths;
- private sound filenames and library paths;
- audio device names that identify personal hardware;
- account names, invite links, chat content, or private game context;
- credentials, tokens, webhook URLs, and private repository URLs.

## Sound Library Checks

For library scanning issues, report:

- configured library directories;
- whether files are under `~/Music/DeckSoundpad`;
- file extensions tested;
- whether files are symlinks;
- whether the setting to allow symlinks outside library roots is enabled.

Do not attach the original sound files unless a maintainer asks for a minimal
test asset and you have permission to share it.

## External Overlay Checks

For overlay issues, include:

- Game Mode or Desktop Mode;
- game tested;
- which rear button is selected for the overlay;
- whether that configured button toggles anything;
- whether Decky panel controls still work;
- relevant redacted lines from `bridge.log` and `external-overlay.log`.

For release validation, copy the final result into
`docs/HARDWARE_VALIDATION.md` or the release checklist issue.

## Security-Sensitive Problems

Do not post exploit details publicly. Follow `SECURITY.md` and use private
vulnerability reporting once the public repository enables it.
