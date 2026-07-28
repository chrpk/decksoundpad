# Installation And Removal

Use this guide for local testing and public ZIP releases. Do not publish a broad
installation claim until `docs/OPEN_SOURCE_READINESS.md` release blockers are
complete.

## Install From A Release ZIP

1. Download `DeckSoundpad-vX.Y.Z-full.zip` and its `.sha256` file from the
   GitHub Release assets. If a release has not been published yet, use the
   tagged `Tagged Release Artifact` workflow artifact for the same tag.
2. Verify that the checksum in the `.sha256` file matches the ZIP you
   downloaded.
3. Install through Decky Loader's plugin developer tools when available.
4. For manual developer installs, extract the `DeckSoundpad/` directory from
   the ZIP into the Decky Loader plugin directory you use for local testing.
5. Restart Decky Loader if the plugin does not appear.
6. Open the Decky panel and confirm the version shown at the top of the
   DeckSoundpad panel matches the release notes.
7. Press Restart DeckSoundpad before selecting `DeckSoundpad mic` in a voice
   app.

Do not install from a generated `dist/` directory alone. The release ZIP also
contains the Python backend, defaults, public docs, license, and
`RELEASE_MANIFEST.json`.

## Update

1. Read the release notes for compatibility, device-access, hardware validation,
   and known-limitations changes.
2. Keep a copy of any custom sound library directories before changing plugin
   versions.
3. Stop active playback and close the external overlay.
4. Install the newer ZIP with the same method used for the previous version.
5. Restart Decky Loader.
6. Open DeckSoundpad and check the visible version/build metadata.
7. Press Restart DeckSoundpad after the update.

Your sound files live in configured local library directories, defaulting to
`~/Music/DeckSoundpad`. Updating the plugin should not delete those files.

## Roll Back

1. Keep the previous release ZIP and checksum until the new version has passed
   your local audio and overlay checks.
2. Reinstall the previous ZIP with the same method used for the update.
3. Restart Decky Loader.
4. Press Restart DeckSoundpad.
5. If the problem was a compatibility regression, include both version numbers,
   SteamOS version, Decky Loader version, and redacted logs in the bug report.

## Uninstall

1. Remove DeckSoundpad through Decky Loader's plugin management UI when
   available.
2. For manual developer installs, remove only the `DeckSoundpad/` plugin
   directory that was extracted from the release ZIP.
3. Restart Decky Loader.
4. Remove mirrored support logs under `~/Public/DeckSoundpad/logs/` if you no
   longer need them.

Uninstalling the plugin should not require deleting your sound library. Keep or
remove `~/Music/DeckSoundpad` according to whether you still want those local
sound files.

## Local Data To Review

DeckSoundpad can leave local data in these areas:

- configured sound library directories, defaulting to `~/Music/DeckSoundpad`;
- Decky-managed plugin settings;
- mirrored support logs under `~/Public/DeckSoundpad/logs/`;
- PipeWire/PulseAudio routing state that is repaired or cleaned up by plugin
  actions.

See `docs/PRIVACY.md` for what those files can contain before sharing logs.

## Recovery

If the Decky panel fails to load after installation:

1. Restart Decky Loader.
2. Remove the manually extracted `DeckSoundpad/` plugin directory if this was a
   developer install.
3. Reinstall the last known-good release ZIP.
4. Include the ZIP filename, checksum, visible version/build metadata if
   available, and redacted `bridge.log` / `backend.log` lines in a bug report.
