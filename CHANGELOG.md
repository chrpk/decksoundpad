# Changelog

All notable changes to DeckSoundpad should be documented here.

This project uses semantic versioning once public releases begin.

## Unreleased

## 1.5.0 - 2026-10-10

### Added

- Overlay tabs: Recent (the last 10 sounds played) and one tab per subfolder of
  the sound folder. L1/R1 still flip pages and move into the next tab at the
  end of one. Tap a tab to jump to it.
- More overlay buttons: X plays and keeps the overlay open, Y stops all sounds,
  and B closes without playing.
- After A plays a sound, a short toast names it so you know it worked; the game
  keeps input while the toast shows.
- Tiles show a playing marker until their sound ends.
- The overlay header shows whether the DeckSoundpad mic is ready, using the
  same checks as the Decky status card.
- Tapping outside the sound grid closes the overlay.
- The README shows screenshots of the overlay, the Decky panel, and Steam's
  input device picker.

### Changed

- R5 replays the most recent sound instead of stepping back one sound in the
  list. It still works with the overlay closed, and is listed in the overlay
  and in the Controls guide.
- Redesigned the overlay for the Deck screen: larger text, near-opaque panels
  and tiles so text stays readable over bright games, a thicker focus ring,
  and a button legend with controller glyphs. Long names wrap to two lines and
  the duplicate footer text is gone.
- The D-pad moves across pages instead of wrapping within one, and flipping
  pages keeps the highlighted row and column.
- Playback errors in the overlay show in red instead of as plain status text.

### Fixed

- Sound names in Japanese, Chinese, Korean, Cyrillic, or with emoji render as
  text instead of boxes. The overlay now lays text out with Pango, which also
  truncates by width instead of by character count.
- Sliding a finger across the overlay no longer plays every tile it passes
  over; only the first touch counts.
- Sounds start sooner. The low-latency player kept about a third of a second
  of silence queued ahead of every sound; it now keeps about 40 ms.
- DeckSoundpad no longer streams silence for the rest of the session after
  the first sound. The player stream closes after a minute without sound and
  reopens on the next one.
- Decoded sounds stay within 64 MB of memory, and only the part that can play
  before the time limit is decoded. Test sound no longer decodes the beep
  again on every press.
- The Decky panel stops polling status while the Quick Access menu is closed.
- The Steam Deck controller monitor reads only Valve HID devices and wakes
  several times less often. Other controllers no longer keep it busy.
- `bridge.log` and `external-overlay.log` roll over at about 500 KB instead of
  growing without limit, and input device errors that repeat every few seconds
  are logged once.
- The optional background healthcheck keeps running after a failed check.

## 1.4.0 - 2026-10-09

### Added

- Test sound button in the Status section plays a short beep through the
  DeckSoundpad mic route, so you can check audio without adding sound files.
- Sound volume slider in Settings, up to 150%.
- Mic volume slider, shown while Real mic passthrough is on, up to 150%. It
  sets only the passthrough level, so other apps still hear the mic at its
  usual level. Its description names the mic in use: the input device selected
  in Steam Settings > Audio.
- Change sound folder button in the Sounds section opens a folder picker. The
  new folder is scanned right away, and an unusable folder is rejected with an
  error while the previous sounds stay available.

### Changed

- Reordered the Decky menu by use: status, sounds, settings, then controls,
  with build info moved to a footer. Restart DeckSoundpad now sits in the
  Status section next to Test sound instead of a separate Recovery section at
  the bottom.
- Errors now show under the status and clear after a successful test sound or
  restart. Status explains what to do when audio needs a restart.
- Buttons show progress while refreshing, testing, or restarting, and an empty
  sound folder explains how to add sounds.

### Fixed

- Sounds play again on current Decky Loader builds. Decky is a PyInstaller
  binary that points `LD_LIBRARY_PATH` at its bundled libraries in
  `/tmp/_MEI...`; audio helpers (`pw-play`, `pacat`, `ffmpeg`, `pactl`) and the
  overlay inherited it and failed with library errors naming `/tmp`. Child
  processes now get the system library path back.
- Playback no longer reports success when the low-latency audio stream dies at
  startup. DeckSoundpad falls back to another player or shows the real error,
  and logs why the stream stopped.
- Sounds no longer go silent and then fail with "maximum concurrent sounds
  reached" when Python's `audioop` module is missing (removed in Python 3.13).
  The low-latency mixer needs it, so DeckSoundpad now plays through the
  per-sound players instead.
- Switching the Steam input device no longer leaves the previous mic mixed in
  next to the new one when DeckSoundpad rebuilds the passthrough.

## 0.1.32 - 2026-10-08

### Fixed

- Overlay hotkeys work again for normal installs. Decky runs plugins as the
  Steam user unless they request the `root` flag, so the readers no longer
  refuse to start when the process is not root; they start for every user and
  skip devices they cannot open.

### Changed

- Moved the in-game and Decky control reference out of the Decky panel body and
  into a "Controls guide" dialog that opens from a button in the Controls
  section.

## 0.1.31 - 2026-10-08

### Added

- Added a `notices:generate` script that builds `docs/THIRD_PARTY_NOTICES.md`
  from installed dependency metadata and a review of `src/` imports.

### Changed

- `docs/THIRD_PARTY_NOTICES.md` is now generated, and
  `corepack pnpm run validate:licenses` fails when it is missing or stale, so
  dependency updates can no longer silently desynchronize the license summary.
  Regenerating reflects the `rollup` 4.62.2 and `@types/react-dom` 19.2.7
  development dependency bumps.
- Updated the pull request template, release checklist, contributor guide, and
  maintainer guide to include the notices regeneration step.

## 0.1.30 - 2026-07-28

### Added

- Added Decky settings dropdowns for choosing L4, L5, R4, or R5 as the
  external-overlay hotkey and selecting a discovered controller input device.
  Explicit controller selection persists via a stable evdev selector and routes
  overlay hotkey/navigation events through that device.
- Added a Deckbrew submission checklist and local validation gate.
- Added public repository, issue tracker, and project homepage package metadata.

### Changed

- Reworked the recovery action into a full DeckSoundpad runtime restart: active
  playback, input listeners, the overlay action server, and the overlay process
  are stopped; input grabs are released; settings are reloaded; audio components
  are recreated; input devices are rediscovered; bridge workers are restarted;
  the route is rebuilt; and sounds are rescanned.
- Made restart completion operation-aware so stale route and healthcheck results
  cannot end frontend polling early, and made failed playback/router cleanup a
  reported restart failure instead of silently abandoning old resources.
- Playback timeout workers are now tracked and cancelled when playback or the
  runtime is closed.
- Shortened and reorganized user/release documentation, removed a stale
  repository-comparison report, and excluded maintainer-only material from the
  runtime ZIP.
- Made repository and secret-scan validators ignore tracked files that have
  been deleted in the working tree.
- Consolidated shared frontend status and error helpers and simplified repeated
  external-overlay ownership and navigation logic.
- Moved pnpm peer-dependency settings to `pnpm-workspace.yaml`, where current
  pnpm releases read project settings.
- Corrected frontend capability descriptions and clarified why two TypeScript
  versions appear in the third-party development dependency notice.
- Updated the open-source readiness tracker for the final repository URL and
  remaining publication evidence.

### Security

- Hardened privileged runtime file handling against symlink replacement and
  reduced overlay sockets to owner-only access.
- Rejected symlinked or non-user-owned custom library roots/files in the
  privileged backend.
- Added a pinned Bandit gate to pull-request CI and tagged release validation.
- Dropped audio-routing, decoding, and playback subprocesses from Decky's root
  context to the Steam user before executing host audio tools.

## 0.1.29 - 2026-06-20

### Changed

- Bumped DeckSoundpad package and backend versions for a tagged GitHub release.
- Updated third-party notices for the current `@types/react` development
  dependency version.

## 0.1.28 - 2026-06-20

### Added

- Open-source readiness tracking, publication runbook, release notes template,
  and reference repository comparison.
- Contribution guide, support policy, security policy, code of conduct, issue
  templates, pull request template, labels, Dependabot configuration, and CI
  workflows.
- Release packaging checks for required runtime files, manifest metadata,
  checksum verification, docs inclusion, and forbidden development artifacts.
- Privacy, diagnostics, compatibility, maintainer, troubleshooting, release
  asset, hardware validation, threat model, and root-permission rationale docs.
- Tests for library symlink escape handling and Decky bridge behavior.

### Changed

- Current pre-public release baseline for DeckSoundpad.
- Decky in-process backend integration.
- PipeWire/PulseAudio virtual microphone routing.
- Local sound library scanning and playback controls.
- Steam Deck simulation mode for backend development.

### Security

- Documented the local-only security model, privileged root-flag rationale,
  log redaction expectations, dependency license notices, and secret-scanning
  release gates.
