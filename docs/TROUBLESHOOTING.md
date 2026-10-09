# Troubleshooting

Use this matrix after pressing Restart DeckSoundpad from the Decky panel.

Logs are mirrored to `~/Public/DeckSoundpad/logs/`. Redact local usernames,
paths, and audio device names before sharing logs publicly.
Use `docs/DIAGNOSTICS.md` for a complete support data checklist.

| Symptom | Check | Likely Cause | Action |
| --- | --- | --- | --- |
| `DeckSoundpad mic` is missing from voice apps | `pactl list sources short \| grep decksoundpad` | PipeWire/PulseAudio route did not initialize | Press Restart DeckSoundpad. If it still fails, attach `backend.log` and `bridge.log` to a bug report. |
| Sound buttons do nothing | Decky panel status and `backend.log` | Backend did not start or no playable sounds were indexed | Press Refresh sounds, verify files are in the sound folder shown in the Sounds section (default `~/Music/DeckSoundpad`), and check supported extensions. |
| MP3/OGG/FLAC files do not play | `backend.log` playback backend lines | SteamOS image lacks an available decoder/player for that format | Try WAV first. For compressed formats, DeckSoundpad needs an available backend such as `ffmpeg` or `mpv`. |
| Sound plays on speakers but not in Discord | Discord input device selector | Voice app is using the real mic instead of the virtual input | Select `DeckSoundpad mic` in the voice app input settings. |
| Real mic is not included | Real mic passthrough toggle and Mic volume description | Mic passthrough is disabled or no real mic was detected | Enable Real mic passthrough and press Restart DeckSoundpad. |
| Wrong mic is mixed in | Mic volume description in Decky settings | DeckSoundpad uses the input device selected in Steam Settings > Audio | Select the mic there, then press Restart DeckSoundpad. |
| Voice or sounds are too quiet | Sound volume and Mic volume sliders | Quiet files or a quiet mic | Raise the slider, up to 150%. Mic volume changes only the passthrough level, not the mic level other apps hear. |
| Audio breaks after sleep/resume | `backend.log` around resume time | PipeWire module graph was reset | Playing a sound starts a route repair; play one and try again after a moment. If audio is still broken, press Restart DeckSoundpad. To repair without playing a sound, set `background_healthcheck_enabled` to `true` in `config.json`; DeckSoundpad then checks the route every 8 seconds. |
| External overlay does not appear | `bridge.log` and `external-overlay.log` | Overlay process, socket, or input hook failed | Press Restart DeckSoundpad. If the overlay still does not appear, restart Decky Loader. Include both logs in bug reports. |
| Configured controller or overlay hotkey does not respond | Controller input dropdown and `bridge.log` input entries | Device disconnected, access differs, or the controller does not expose `BTN_GRIP*` rear-button events | Reopen Settings and choose the device again or select Automatic. Try another rear-button mapping and report the evdev codes from `bridge.log`. |
| Library includes unexpected files | Sound count in the Sounds section and the overlay sound list | Sound folder contains symlinks or nested folders | Symlinks that point outside the sound folder are ignored by default. Check the folder shown in the Sounds section, or pick another with Change sound folder. |

## Audio Route Check

From Desktop Mode Konsole:

```bash
pactl list sources short | grep decksoundpad
```

Expected result: a source named `decksoundpad_mic` appears.

- If `pactl info` hangs or times out, the blocker is PipeWire/PulseAudio state,
  not the Decky UI.
- If no `decksoundpad_mic` source appears, the virtual source was not created.
  Press Restart DeckSoundpad again and check the logs in
  `~/Public/DeckSoundpad/logs/`.
- If the source appears but voice app meters do not react when a sound plays,
  attach `backend.log` and `bridge.log` to a bug report.
