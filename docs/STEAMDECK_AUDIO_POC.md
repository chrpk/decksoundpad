# Steam Deck Audio PoC

This PoC tests only the core audio idea. It does not start Decky, the daemon, or
the web UI.

Run it from Desktop Mode Konsole on the Steam Deck:

```bash
cd /path/to/DeckSoundpad
scripts/poc_steamdeck_audio.sh
```

Expected result:

- `DeckSoundpad mic` exists as an input source.
- If a real mic is detected, it is looped into the internal DeckSoundpad mix bus.
- The bundled `ready-chime.wav` plays into `DeckSoundpad mic`.
- Selecting `DeckSoundpad mic` in Discord, Steam Voice, or another voice app
  shows input meter activity when the sample plays.

Verify the virtual input through Pulse/PipeWire first:

```bash
pactl list sources short | grep decksoundpad
pactl get-default-source
```

`DeckSoundpad mic` should appear as the source name `decksoundpad_mic`. Some
SteamOS/KDE settings screens may not show virtual Pulse sources immediately, but
voice apps that enumerate Pulse/PipeWire inputs should see it after the source
appears in `pactl`.

Useful options:

```bash
DECKSOUNDPAD_POC_SKIP_PLAY=1 scripts/poc_steamdeck_audio.sh
DECKSOUNDPAD_POC_TIMEOUT=15 scripts/poc_steamdeck_audio.sh
```

Cleanup:

```bash
scripts/poc_reset_audio.sh
```

Pass/fail interpretation:

- If `pactl info` hangs or times out, the blocker is PipeWire/PulseAudio state,
  not Decky UI.
- If `pactl list sources short | grep decksoundpad` shows nothing, the virtual
  source was not created. Re-run the PoC and check
  `.tmp-run/poc/steamdeck-audio-poc.log`.
- If `DeckSoundpad mic` appears but meters do not react, the virtual-source graph
  needs a different PipeWire implementation.
- If the PoC works in Konsole, then the product should be built by wrapping this
  audio path safely behind manual Decky actions.
