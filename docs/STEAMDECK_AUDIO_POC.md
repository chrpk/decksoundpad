# Steam Deck Audio PoC

This check verifies the core audio route after DeckSoundpad has initialized the
backend and repaired audio routing from the Decky panel.

Open Decky, select DeckSoundpad, and run Repair audio routing. Then run the
verification commands below from Desktop Mode Konsole on the Steam Deck.

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

Pass/fail interpretation:

- If `pactl info` hangs or times out, the blocker is PipeWire/PulseAudio state,
  not Decky UI.
- If `pactl list sources short | grep decksoundpad` shows nothing, the virtual
  source was not created. Press Repair audio routing again and inspect the
  public logs in `~/Public/DeckSoundpad/logs/`.
- If `DeckSoundpad mic` appears but meters do not react, the virtual-source graph
  needs a different PipeWire implementation.
- If the route works in Konsole, then Decky controls should be able to send
  soundboard playback into `DeckSoundpad mic`.
