# Deckbrew Submission Evidence

Fill this file, or link to an equivalent release issue, before opening the
Decky Plugin Database pull request. Do not mark an item complete without a URL,
file path, or command output that reviewers can inspect.

## Repository

- Public repository URL:
- Submitted commit SHA:
- Decky Plugin Database pull request URL:
- Submodule path in the database repository: `plugins/`

## Deckbrew Policy Evidence

- License file: `LICENSE`
- Black-box binary review evidence:
- Obfuscation/minified-code review evidence:
- Keyshop-link review evidence:
- Monetization/paid-feature review evidence:
- LLM/code-provenance evidence:

## Backend Checklist

- Custom backend other than Python: No
- Third-party FOSS tool without statically linked dependencies: Yes
  - Evidence: SteamOS/PipeWire/PulseAudio tools such as `pactl` and `pw-play`
    are called when available; optional local playback tools such as `ffmpeg`
    or `mpv` are not bundled in the ZIP.
- Custom statically linked binary: No

## Steam Deck Validation

- Steam Deck model:
- SteamOS branch and version:
- Decky Loader version:
- Stable/Beta/Preview requirement decision:
- `docs/HARDWARE_VALIDATION.md` evidence:
- `docs/STEAMDECK_AUDIO_POC.md` evidence:
- `docs/EXTERNAL_OVERLAY_POC.md` evidence:
- Minimum supported SteamOS version:
- Minimum supported Decky Loader version:
- Root flag decision: `keep`, `remove`, or `split`

## Store Media And Release Artifact

- `plugin.json` `publish.image` HTTPS PNG URL:
- README screenshot or demo media URL:
- Release artifact URL:
- Release checksum URL:
- Tagged artifact workflow URL:
