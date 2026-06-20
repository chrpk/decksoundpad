# Troubleshooting

Use this matrix after pressing Repair audio routing from the Decky panel.

Logs are mirrored to `~/Public/DeckSoundpad/logs/`. Redact local usernames,
paths, and audio device names before sharing logs publicly.
Use `docs/DIAGNOSTICS.md` for a complete support data checklist.

| Symptom | Check | Likely Cause | Action |
| --- | --- | --- | --- |
| `DeckSoundpad mic` is missing from voice apps | `pactl list sources short \| grep decksoundpad` | PipeWire/PulseAudio route did not initialize | Press Repair audio routing. If it still fails, attach `backend.log` and `bridge.log` to a bug report. |
| Sound buttons do nothing | Decky panel status and `backend.log` | Backend did not start or no playable sounds were indexed | Press Refresh library, verify files are under `~/Music/DeckSoundpad`, and check supported extensions. |
| MP3/OGG/FLAC files do not play | `backend.log` playback backend lines | SteamOS image lacks an available decoder/player for that format | Try WAV first. For compressed formats, DeckSoundpad needs an available backend such as `ffmpeg` or `mpv`. |
| Sound plays on speakers but not in Discord | Discord input device selector | Voice app is using the real mic instead of the virtual input | Select `DeckSoundpad mic` in the voice app input settings. |
| Real mic is not included | Decky setting and status card | Mic passthrough is disabled or no real mic was detected | Enable Real mic passthrough and press Repair audio routing. |
| Audio breaks after sleep/resume | `backend.log` around resume time | PipeWire module graph was reset | Press Repair audio routing. Keep auto repair enabled unless it causes repeated errors. |
| External overlay does not appear | `bridge.log` and `external-overlay.log` | Overlay process, socket, or input hook failed | Restart Decky Loader, then retry. Include both logs in bug reports. |
| L5 overlay hotkey does not respond | `bridge.log` input monitor entries | Input device access differs across SteamOS/controller stacks | Test from Decky panel first. Report SteamOS version, Deck model, and whether root flag is enabled. |
| Library includes unexpected files | Sound list categories | Library directory contains symlinks or nested folders | Symlinks escaping configured roots are ignored by default. Check custom library directories in settings. |

## Audio Route Check

From Desktop Mode Konsole:

```bash
pactl list sources short | grep decksoundpad
```

Expected result: a source named `decksoundpad_mic` appears.

For pass/fail criteria, use `docs/STEAMDECK_AUDIO_POC.md`.
