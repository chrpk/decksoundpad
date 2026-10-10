# Support

Run **Restart DeckSoundpad** before reporting a bug. If the problem remains,
follow [the diagnostics guide](docs/DIAGNOSTICS.md). For a prerelease build,
reply through the channel that provided it. Once the repository is public, open
a GitHub issue.

Include:

- DeckSoundpad version and install method
- Steam Deck model, SteamOS version, and Decky Loader version
- Game Mode or Desktop Mode
- The app or game you tested
- What you expected and what happened
- Relevant lines from `bridge.log`, `backend.log`, or `external-overlay.log`

For audio problems, say whether this command shows `decksoundpad_mic`:

```bash
pactl list sources short | grep decksoundpad
```

For overlay problems, include the selected controller and rear button.

Logs can contain usernames, paths, filenames, and device names. Redact them.
Do not upload private sounds, recordings, credentials, tokens, or unrelated
log lines. See [privacy](docs/PRIVACY.md) for details.

Do not include vulnerability details in a public issue. Follow [SECURITY.md](SECURITY.md)
for the available private-reporting or contact-request process.
