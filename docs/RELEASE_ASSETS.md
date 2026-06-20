# Release Assets

Use this guide when preparing screenshots, demo clips, and Decky Store media for
a public DeckSoundpad release.

## Required Public Assets

For the first public release, capture or attach:

- Decky panel status view after audio repair;
- sound grid with safe sample names;
- settings view;
- voice app input selector showing `DeckSoundpad mic`;
- external overlay over a non-sensitive game or test scene;
- optional short demo clip showing overlay navigation and playback.

The screenshots can be committed to the repository or attached to the GitHub
release. Record their final paths or URLs in the release checklist issue and in
`docs/HARDWARE_VALIDATION.md`.

## Privacy Rules

Before publishing assets:

- remove usernames, home-directory paths, account names, invite links, private
  game lobbies, and chat content;
- use safe sample sound names that do not expose private files;
- avoid screenshots of personal Discord servers, Steam friends, or browser
  tabs;
- crop only when it does not hide relevant UI state;
- do not include voice recordings unless they are synthetic or explicitly safe
  to publish.

## Decky Store Image

Decky Store or plugin-index submission requires `plugin.json` `publish.image`
to point to an HTTPS PNG URL. Do not add a placeholder image URL.

Before store submission:

```bash
DECKSOUNDPAD_REQUIRE_PUBLISH_IMAGE=1 corepack pnpm run validate:release
```

The image should clearly identify DeckSoundpad as a Steam Deck soundboard and
should not contain private names, copyrighted game art as the primary subject,
or unreadable small text.

## Suggested File Names

Use predictable, lowercase names if assets are committed:

- `docs/assets/decksoundpad-panel.png`
- `docs/assets/decksoundpad-sound-grid.png`
- `docs/assets/decksoundpad-settings.png`
- `docs/assets/decksoundpad-voice-input.png`
- `docs/assets/decksoundpad-overlay.png`
- `docs/assets/decksoundpad-demo.webm`

If assets are attached only to a release, keep the same base names.

Committed screenshots and demo clips are repository or GitHub Release assets,
not runtime plugin files. `scripts/package_plugin.sh` packages Markdown docs
only, and `corepack pnpm run validate:release` rejects `docs/assets/` or docs
media files inside the plugin ZIP.

## Validation Record

Release notes should include:

- where each screenshot or demo asset is stored;
- whether assets were captured on real Steam Deck hardware;
- SteamOS and Decky Loader versions used for capture;
- whether the image used for `publish.image` is the same as a committed or
  attached asset.
