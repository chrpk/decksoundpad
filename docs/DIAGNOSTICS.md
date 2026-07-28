# Diagnostics

Use this checklist after **Restart DeckSoundpad** and reproducing the problem
once. Share only what helps explain the bug.

Never attach private sounds, recordings, credentials, tokens, webhook URLs, or
unredacted logs.

## System details

Include:

- DeckSoundpad version or commit and install method
- Steam Deck model, SteamOS version, and Decky Loader version
- Game Mode or Desktop Mode
- The game or voice app tested
- Whether the app selected `DeckSoundpad mic`

## Audio checks

Run these in Desktop Mode Konsole:

```bash
pactl info
pactl list sources short
pactl list sinks short
pactl list modules short | grep -i decksoundpad
pactl get-default-source
```

Paste only relevant lines.

## Logs

```text
~/Public/DeckSoundpad/logs/bridge.log
~/Public/DeckSoundpad/logs/backend.log
~/Public/DeckSoundpad/logs/external-overlay.log
```

Redact usernames, home-directory paths, private filenames, library paths,
device names, account names, invite links, chat content, credentials, tokens,
and private repository URLs.

## Library problems

Include the configured library directory, tested file extensions, and whether
the files or directories are symlinks. Do not attach the original files unless
a maintainer asks for a small test asset that you may legally share.

## Overlay problems

Include the mode, game, selected controller, rear-button mapping, whether the
button reacts at all, and relevant lines from `bridge.log` and
`external-overlay.log`.

Release maintainers should copy final hardware results to
[the repository hardware-validation checklist](https://github.com/chrpk/decksoundpad/blob/main/docs/HARDWARE_VALIDATION.md).

## Security problems

Do not post exploit details publicly. Follow [SECURITY.md](../SECURITY.md) for
the available private-reporting or contact-request process.
