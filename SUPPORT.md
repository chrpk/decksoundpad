# Support

Use GitHub issues for reproducible bugs, feature requests, and release
validation once the public repository exists.

Before opening an issue:

- Run Repair audio routing from the Decky panel.
- Check `~/Public/DeckSoundpad/logs/bridge.log`.
- Check `~/Public/DeckSoundpad/logs/backend.log`.
- Redact local usernames, paths, and audio device names from logs.
- Do not upload private sound files or voice recordings.

Privacy and local data handling are documented in `docs/PRIVACY.md`.
Safe diagnostic collection is documented in `docs/DIAGNOSTICS.md`.

For audio routing problems, include:

- DeckSoundpad version or commit.
- Installation source.
- Steam Deck model.
- SteamOS version.
- Decky Loader version.
- Whether `pactl list sources short | grep decksoundpad` shows
  `decksoundpad_mic`.
- Whether the target voice app selected `DeckSoundpad mic`.

For external overlay problems, include:

- Game Mode or Desktop Mode.
- Game tested.
- Whether the configured overlay button toggles anything.
- Which button is selected under Decky > DeckSoundpad > Settings.
- Relevant lines from `bridge.log` and `external-overlay.log`.

Do not report vulnerabilities in public issues. Follow `SECURITY.md` for
security-sensitive reports.
