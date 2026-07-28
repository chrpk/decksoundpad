# Troubleshooting

Use this matrix after pressing Restart DeckSoundpad from the Decky panel.

Logs are mirrored to `~/Public/DeckSoundpad/logs/`. Redact local usernames,
paths, and audio device names before sharing logs publicly.
Use `docs/DIAGNOSTICS.md` for a complete support data checklist.

| Symptom | Check | Likely Cause | Action |
| --- | --- | --- | --- |
| `DeckSoundpad mic` is missing from voice apps | `pactl list sources short \| grep decksoundpad` | PipeWire/PulseAudio route did not initialize | Press Restart DeckSoundpad. If it still fails, attach `backend.log` and `bridge.log` to a bug report. |
| Sound buttons do nothing | Decky panel status and `backend.log` | Backend did not start or no playable sounds were indexed | Press Refresh library, verify files are under `~/Music/DeckSoundpad`, and check supported extensions. |
| MP3/OGG/FLAC files do not play | `backend.log` playback backend lines | SteamOS image lacks an available decoder/player for that format | Try WAV first. For compressed formats, DeckSoundpad needs an available backend such as `ffmpeg` or `mpv`. |
| Sound plays on speakers but not in Discord | Discord input device selector | Voice app is using the real mic instead of the virtual input | Select `DeckSoundpad mic` in the voice app input settings. |
| Real mic is not included | Decky setting and status card | Mic passthrough is disabled or no real mic was detected | Enable Real mic passthrough and press Restart DeckSoundpad. |
| Audio breaks after sleep/resume | `backend.log` around resume time | PipeWire module graph was reset | Press Restart DeckSoundpad. Keep auto repair enabled unless it causes repeated errors. |
| External overlay does not appear | `bridge.log` and `external-overlay.log` | Overlay process, socket, or input hook failed | Restart Decky Loader, then retry. Include both logs in bug reports. |
| Configured controller or overlay hotkey does not respond | Controller input dropdown and `bridge.log` input entries | Device disconnected, access differs, or the controller does not expose `BTN_GRIP*` rear-button events | Reopen Settings and choose the device again or select Automatic. Try another rear-button mapping and report the evdev codes from `bridge.log`. |
| Library includes unexpected files | Sound list categories | Library directory contains symlinks or nested folders | Symlinks escaping configured roots are ignored by default. Check custom library directories in settings. |

## Audio Route Check

From Desktop Mode Konsole:

```bash
pactl list sources short | grep decksoundpad
```

Expected result: a source named `decksoundpad_mic` appears.

For pass/fail criteria, use `docs/STEAMDECK_AUDIO_POC.md`.
