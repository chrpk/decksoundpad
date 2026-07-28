# Install, update, or remove DeckSoundpad

## Install From A Release ZIP

1. Download `DeckSoundpad-vX.Y.Z-full.zip` and its `.sha256` file from the same
   GitHub Release.
2. Verify that the checksum matches the ZIP.
3. Install the ZIP with Decky Loader's plugin developer tools. For a manual
   developer install, extract its `DeckSoundpad/` directory into your Decky
   plugin directory.
4. Restart Decky Loader if the plugin does not appear.
5. Check the visible version/build metadata at the top of the panel.
6. Select **Restart DeckSoundpad**, then choose `DeckSoundpad mic` in your voice
   app.

Do not install `dist/` by itself. The release ZIP also contains the Python
backend, defaults, docs, license, and `RELEASE_MANIFEST.json`.

## Update

1. Keep your previous ZIP until the new version works on your Deck.
2. Install the new ZIP the same way you installed the old one.
3. Restart Decky Loader, verify the visible version/build metadata, and select
   **Restart DeckSoundpad**.

Sounds live outside the plugin, usually in `~/Music/DeckSoundpad`. Updating the
plugin should not delete those files.

## Roll Back

Reinstall the previous ZIP, restart Decky Loader, and select **Restart
DeckSoundpad**. In a bug report, include both plugin versions and redacted
logs.

## Uninstall

Remove DeckSoundpad through Decky Loader. For a manual install, remove only the
extracted `DeckSoundpad/` plugin directory, then restart Decky Loader.

Uninstalling should not require deleting your sound library. Keep or remove
`~/Music/DeckSoundpad` separately.

## Local Data To Review

DeckSoundpad can leave:

- sounds in configured library directories;
- Decky-managed settings;
- logs in `~/Public/DeckSoundpad/logs/`;
- temporary PipeWire/PulseAudio routing state.

Delete logs if you no longer need them. Review [privacy](PRIVACY.md) before
sharing any local data.

## Recovery

If the panel no longer loads:

1. Restart Decky Loader.
2. Reinstall the last known-good release ZIP.
3. If a manual install is broken, remove only its extracted plugin directory
   before reinstalling.
4. Report the ZIP filename, checksum, visible version/build metadata, and
   redacted `bridge.log` / `backend.log` lines.
