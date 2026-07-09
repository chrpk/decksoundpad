# Release Notes Template

Use this template for GitHub Releases after the tagged artifact workflow and
hardware validation are complete. Replace every placeholder before publishing.

## DeckSoundpad vX.Y.Z

Release commit: `<40-character commit SHA>`
Artifact: `DeckSoundpad-vX.Y.Z-full.zip`
Checksum: `<sha256>  DeckSoundpad-vX.Y.Z-full.zip`

The checksum applies to the exact uploaded ZIP from the tagged release workflow.
Do not replace it with a checksum from a later local rebuild; the release
manifest records `generatedAt`, so rebuilds are intentionally build-specific.

## Summary

- User-facing change 1.
- User-facing change 2.
- Maintenance or packaging change.

## Compatibility

- SteamOS tested: `<version>`
- Decky Loader tested: `<version>`
- Minimum supported SteamOS: `<version or unknown>`
- Minimum supported Decky Loader: `<version or unknown>`
- Compatibility evidence: see `docs/HARDWARE_VALIDATION.md` in this release.

## Hardware Validation

- Real microphone detected: `<yes/no>`
- `DeckSoundpad mic` visible in voice app: `<yes/no>`
- Soundboard audio reaches `DeckSoundpad mic`: `<yes/no>`
- Real mic passthrough mixed with soundboard: `<yes/no>`
- External overlay opens and plays sounds in game mode: `<yes/no>`
- Sleep/resume recovery verified with Repair audio routing: `<yes/no>`

## Root Flag Review

- `flags: ["root"]` remains required: `<yes/no>`
- Evidence summary: `<what failed without root, or why the flag was removed>`
- Rationale: see `docs/ROOT_PERMISSION_RATIONALE.md`.

## Release Assets

- Panel screenshot: `<path or release attachment>`
- Sound grid screenshot: `<path or release attachment>`
- Settings screenshot: `<path or release attachment>`
- Voice input screenshot: `<path or release attachment>`
- Overlay screenshot or demo clip: `<path or release attachment>`
- Decky Store image: `<plugin.json publish.image URL or not applicable>`

## Validation

- Local release validation: `<command and result>`
- Python security scan: `<Bandit version and result>`
- Tagged Release Artifact workflow: `<workflow run URL>`
- Dependency Review workflow: `<workflow run URL or not applicable>`
- Full-history secret scan: `<tool/workflow and result>`
- Publication readiness gate: `<corepack pnpm run validate:publication result>`
- Dependency license review: `<result from corepack pnpm run validate:licenses>`
- Package inspection: `<result from corepack pnpm run validate:release>`

## Manifest

Paste `DeckSoundpad/RELEASE_MANIFEST.json` from inside the ZIP:

```json
{
  "name": "DeckSoundpad",
  "packageName": "decksoundpad",
  "version": "X.Y.Z",
  "backendVersion": "X.Y.Z",
  "apiVersion": 1,
  "flags": ["root"],
  "artifact": "DeckSoundpad-vX.Y.Z-full.zip",
  "sourceCommit": "<40-character commit SHA>",
  "sourceDirty": false,
  "generatedAt": "<timestamp>"
}
```

## Known Limitations

- Hardware or OS limitation.
- Audio routing limitation.
- Overlay limitation.

## Install

Download `DeckSoundpad-vX.Y.Z-full.zip` and install it through Decky Loader's
plugin developer tools or extract it into Decky's plugin directory for local
testing.

Use `docs/INSTALLATION.md` for update, rollback, uninstall, and recovery
guidance.

## Security And Privacy

DeckSoundpad has no LAN API and stores local configuration/logs on the Steam
Deck. Redact usernames, paths, sound names, and device names before posting
logs publicly. Security reports should follow `SECURITY.md`.
