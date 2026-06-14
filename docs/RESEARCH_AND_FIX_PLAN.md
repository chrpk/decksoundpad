# DeckSoundpad Research and Fix Plan

Date: 2026-06-13

## Scope

User report: "nothing works as needed." This research focused on making the
failure modes concrete before implementation work.

`gsd-plan-phase` could not run in this repository because:

- `.planning/` does not exist.
- `gsd-sdk` is not available in the shell.

The GSD pre-flight gate therefore blocks phase planning. This document is the
fallback research and repair plan for the current repository.

## Internet Research Summary

Primary sources checked:

- Decky plugin docs:
  https://wiki.deckbrew.xyz/plugin-dev/getting-started
- PipeWire PulseAudio module docs:
  https://docs.pipewire.org/page_man_pipewire-pulse-modules_7.html
- PipeWire pulse module pages:
  https://docs.pipewire.org/page_pulse_module_null_sink.html
  https://docs.pipewire.org/page_pulse_module_remap_source.html
  https://docs.pipewire.org/page_pulse_module_virtual_source.html
  https://www.mankier.com/7/pipewire-pulse-module-loopback
- Native PipeWire loopback docs:
  https://docs.pipewire.org/page_module_loopback.html
- Python `http.server` docs:
  https://docs.python.org/3/library/http.server.html
- pnpm installation docs:
  https://pnpm.io/installation

Reference plugins cloned for local inspection:

- SteamDeckHomebrew/decky-plugin-template:
  https://github.com/SteamDeckHomebrew/decky-plugin-template
- DeckSettings/decky-virtual-surround-sound:
  https://github.com/DeckSettings/decky-virtual-surround-sound
- jacklu97/SteamDeck-VolumeMixer:
  https://github.com/jacklu97/SteamDeck-VolumeMixer
- saumya-banthia/volume-boost:
  https://github.com/saumya-banthia/volume-boost
- DeckThemes/SDH-AudioLoader:
  https://github.com/DeckThemes/SDH-AudioLoader

Research conclusions:

- Decky expects a plugin layout centered around `plugin.json`, `package.json`,
  `main.py`, and `src/index.tsx`. The Python backend exposes async methods on a
  `Plugin` class, and frontend code calls backend methods through Decky APIs.
  This repository follows that broad model.
- Decky docs warn that the `root` flag should only be used when actually
  required. The current no-root approach is aligned with the docs; do not add
  root as a shortcut for audio repair unless Steam Deck testing proves it is
  strictly necessary.
- Decky docs say frontend dependencies are managed by pnpm. pnpm's own docs
  recommend Corepack as a valid way to install/manage pnpm for Node projects,
  including pinning the package manager via `packageManager`. The README should
  document either `corepack enable` or `corepack pnpm ...` so setup is
  reproducible.
- PipeWire's PulseAudio emulation supports loading built-in pulse modules using
  PulseAudio clients such as `pactl load-module`. The current architecture
  using `module-null-sink`, `module-loopback`, `module-remap-source`, and
  `module-virtual-source` is therefore a valid first path on PipeWire systems,
  as long as the modules are supported by the installed PipeWire version.
- PipeWire docs list `sink_name` and `source_name` naming constraints. Current
  names `decksoundpad_sink` and `decksoundpad_mic` fit the documented allowed
  character set.
- PipeWire's native `libpipewire-module-loopback` can also create links,
  virtual sinks, virtual sources, and channel remaps. This is a fallback or
  future implementation path if Steam Deck testing shows the Pulse-compatible
  `pactl` modules behave poorly.
- Python's `BaseHTTPRequestHandler` dispatches requests to `do_METHOD`
  handlers. `SimpleHTTPRequestHandler` implements `do_HEAD` by sending the same
  headers as GET without a body. Because this project uses a custom handler, it
  must implement `do_HEAD` explicitly if HEAD probes should work.

## Reference Plugin Basis

### Use as primary basis

1. `decky-plugin-template` - official current Decky shape.
   - License: BSD-3-Clause.
   - Keep using `@decky/api` `callable(...)` and `definePlugin(...)`.
   - Keep `main.py` async methods on `Plugin`.
   - Keep `_unload` and `_uninstall` cleanup hooks explicit.
   - This project already follows the modern dependency direction
     (`@decky/api`, `@decky/ui`, `@decky/rollup`) better than older plugins that
     still use `decky-frontend-lib`.

2. `decky-virtual-surround-sound` - best reference for audio-device lifecycle.
   - License: BSD-3-Clause.
   - Useful patterns:
     - no Decky root flag for audio-device work
     - controlled subprocess environment based on current UID:
       `XDG_RUNTIME_DIR=/run/user/<uid>` and DBus session address
     - background task with cancellation in `_unload`
     - wait loops that verify a PipeWire/Pulse sink appears before reporting
       success
     - pid files and cleanup for long-lived audio graph processes
     - `pactl -f json list ...` first, with fallback to text parsing when JSON
       has decode/name issues
     - explicit diagnostics when sink/object metadata is missing
   - Do not copy the filter-chain implementation directly; DeckSoundpad needs a
     virtual input/mix path, not a surround output filter. Borrow lifecycle,
     env, diagnostics, and wait/cleanup patterns.

3. `volume-boost` - small reference for simple `pactl` command execution.
   - License: BSD-3-Clause.
   - Useful patterns:
     - command args passed as lists, not shell strings
     - short subprocess timeouts
     - structured success/failure returns to frontend
   - Avoid hardcoding `/run/user/1000`; use `os.getuid()` or Decky-provided
     user context.

4. `SteamDeck-VolumeMixer` - reference for sink-input discovery and app stream
   control.
   - License: MIT.
   - Useful patterns:
     - `XDG_RUNTIME_DIR` handling is necessary for `pactl` inside Decky.
     - exposing small backend methods mapped to clear UI actions works well.
   - Avoid copying its shell-string subprocess wrapper. For DeckSoundpad, use
     list-based `create_subprocess_exec` or existing `run_capture(...)` helpers
     to avoid shell quoting problems.

### Use only as conceptual reference

5. `SDH-AudioLoader`.
   - Its checked `LICENSE` file starts with MIT text, but `package.json`
     declares `GPL-2.0-or-later`; treat this as license-ambiguous unless
     resolved upstream.
   - It uses a Decky root flag because it replaces Steam UI sound assets.
   - DeckSoundpad should not copy this code or adopt root. The useful idea is
     only the pack/config scanning model if we later add downloadable sound
     packs.

## Adopted Reference Approach

The implementation basis should be:

- Decky shell: official `decky-plugin-template`.
- Audio lifecycle and diagnostics: `decky-virtual-surround-sound`.
- Simple `pactl` command style: `volume-boost`, adjusted to avoid hardcoded UID.
- App/sink-input awareness if needed later: `SteamDeck-VolumeMixer`.
- Sound pack UX only if needed later: AudioLoader concepts, not code.

The immediate code direction is not to replace the current daemon with copied
plugin code. Instead, refactor DeckSoundpad toward the proven patterns above:
typed Decky callables, deterministic subprocess env, JSON-first pactl parsing,
verified async repair completion, explicit cleanup, and reproducible smoke
tests.

## Verified Baseline

Commands run:

- `python3 -m unittest discover backend/tests` - passed, 43 tests.
- `pnpm run build` - failed because `pnpm` is not on PATH.
- `corepack pnpm run build` - passed, Rollup created `dist`.
- `scripts/package_plugin.sh` - created `out/DeckSoundpad-v0.1.0.zip`.
- `scripts/dev_simulate_macos.sh` - daemon started, but the printed URL was not
  reliable when the requested port was already occupied.
- Simulation API on the actual session port handled:
  - `GET /healthz`
  - `GET /api/v1/status/quick`
  - `GET /`
  - `POST /api/v1/sounds/refresh`
  - `POST /api/v1/play`
  - `POST /api/v1/audio/repair`

## Main Findings

### 1. Simulation prints the requested port, not the actual port

`scripts/dev_simulate_macos.sh` prints `http://127.0.0.1:${PORT}/` before the
daemon binds. The backend can silently choose another port when `auto_port` is
enabled.

Observed run:

- Script printed `8797`.
- `.tmp-run/macos-sim/runtime/session.json` reported actual port `8787`.
- `8797` was already held by another Python process and returned unrelated
  responses.

Relevant code:

- `scripts/dev_simulate_macos.sh:40-47` prints the desired port.
- `backend/decksoundpad/api_server.py:513-532` auto-selects fallback ports.
- `backend/decksoundpad/api_server.py:535-547` writes the real port to
  `session.json`.

Impact: local simulation appears broken even when the daemon is healthy.

### 2. Repair is asynchronous but UI treats the first response as final enough

`POST /api/v1/audio/repair` intentionally returns immediately with
`last_error="Audio repair started"`, then finishes in a background thread.

Relevant code:

- `backend/decksoundpad/api_server.py:171-185` stores and returns the started
  status.
- `src/components/StatusCard.tsx:72-77` calls `repairAudio()` and stores that
  immediate status.
- `src/api/decky.ts:35-43` uses short timeouts around status and repair calls.
- `web/src/main.ts:50-53` triggers repair, then immediately refreshes status.

Observed run:

- `POST /api/v1/audio/repair` returned `Audio repair started`.
- One second later, `GET /api/v1/status` returned ready simulated audio:
  sink, virtual mic, and loopback were all true.

Impact: users can see stale or misleading "Needs repair" / "started" states
even after the audio graph becomes ready.

### 3. Auth contract is inconsistent

The current server authorizes every API request:

- `backend/decksoundpad/api_server.py:409-411`

README says LAN web UI is unauthenticated:

- `README.md:87-88`

But older docs/scripts still assume token auth:

- `DEVELOPMENT_PLAN.md:28`
- `scripts/smoke_test.sh:4-10`

Impact: smoke tests are wrong for the current product contract, and dead token
code creates confusion about whether unauthenticated LAN control is intentional.

### 4. README commands are not reproducible in this environment

README says:

- `pnpm i`
- `pnpm run build`

On this machine, `pnpm` is not on PATH, but `corepack pnpm` works.

Impact: a clean developer can fail before reaching the real app checks.

### 5. HTTP HEAD is unsupported

`curl -I http://127.0.0.1:<port>/` returns `501 Unsupported method ('HEAD')`
because the handler only implements GET/POST/PATCH.

Impact: common health probes and quick manual checks report failure even when
the web UI is available through GET.

### 6. Sleep/resume repair is not active by default

`auto_repair_on_resume` defaults true, but the background healthcheck loop only
runs when `background_healthcheck_enabled` is true. The default config disables
background healthcheck.

Relevant code:

- `backend/decksoundpad/api_server.py:561-585`
- `defaults/config.default.json`

Impact: the README troubleshooting path is manual repair, but the development
plan's sleep/resume repair goal is not actually enabled by default.

### 7. Unit tests are green but miss the broken paths

The test suite does not currently fail for:

- printed simulation URL mismatching actual session port
- smoke script requiring removed token auth
- UI waiting for final audio readiness after repair
- HEAD support for web/static routes
- package smoke against the generated ZIP

Impact: `unittest` passing is not enough to prove MVP readiness.

## Fix Plan

### Phase 1 - Make local simulation trustworthy

Objective: `scripts/dev_simulate_macos.sh` should always tell the developer the
URL that actually works.

Tasks:

1. Update simulation startup to avoid stale-port ambiguity.
   - Option A: set `auto_port=false` for simulation and fail fast if requested
     port is occupied.
   - Option B: keep auto-port, but print the actual port after reading
     `.tmp-run/macos-sim/runtime/session.json`.
   - Prefer Option A for predictability.
2. Add a simulation smoke script that starts the daemon, reads `session.json`,
   then checks healthz, status, web root, refresh, play, and repair.
3. Update README macOS simulation instructions to use the actual session URL
   and mention `corepack pnpm` where needed.
4. Add a preflight check that detects an existing listener on the requested
   simulation port and reports the owning PID before starting.

Verification:

- Starting simulation with the requested port free prints and serves the same
  port.
- Starting simulation with the requested port occupied exits with a clear
  message or prints the real fallback port.
- `python3 -m unittest discover backend/tests` passes.
- New simulation smoke script passes.

### Phase 2 - Fix repair readiness UX

Objective: after clicking repair, Decky UI and web UI should wait for a final
ready/failure state instead of showing the intermediate started status as the
result.

Tasks:

1. Add a small polling helper for Decky UI:
   - call `repairAudio()`
   - poll `getStatus()` until `last_error` is no longer `Audio repair started`
     or `Audio initialization already running`
   - stop when ready, failed, or timeout reached
2. Apply the same readiness flow to `web/src/main.ts`.
3. Consider exposing a backend task state if polling raw status is too vague.
4. Increase or remove fragile UI timeouts where the backend already returns
   quickly but readiness is asynchronous.
5. Borrow the `decky-virtual-surround-sound` readiness pattern: after starting
   repair, poll for the actual audio objects and only surface "Ready" when the
   sink/source/loopback are present.

Verification:

- In simulation, repair button ends at `Ready`, not `Audio repair started`.
- When the router blocks or fails, UI shows a clear failure/timeout.
- Add tests around repair status transition in frontend helper logic if the
  project test stack supports it; otherwise cover through simulation smoke.

### Phase 3 - Resolve auth and smoke-test contract

Objective: docs, smoke scripts, and server behavior must agree.

Tasks:

1. Choose one product contract:
   - unauthenticated LAN-only control, matching current README and tests
   - or token-protected web/API control
2. If LAN-only remains the contract:
   - update `DEVELOPMENT_PLAN.md`
   - update `scripts/smoke_test.sh` to remove `DECKSOUNDPAD_TOKEN`
   - remove or explicitly mark unused token helpers as future/unused
3. If token auth is restored:
   - implement `_authorized`
   - expose token flow in `/api/v1/web-access`
   - update Decky UI and web UI calls
   - update README security section

Verification:

- `scripts/smoke_test.sh` passes against simulation and real daemon.
- README, tests, and server behavior all describe the same auth model.
- Security section explicitly states the LAN exposure model and its risk.

### Phase 4 - Make HTTP and diagnostics less misleading

Objective: common checks should not report false failure.

Tasks:

1. Implement `do_HEAD` for `/`, static assets, and `/healthz`.
2. Make `/api/v1/diagnostics` report both configured and actual web ports.
3. Add a status field that distinguishes:
   - daemon unavailable
   - daemon starting
   - audio repair running
   - audio ready
   - audio unavailable because `pactl`/PipeWire is missing
4. Add tests that verify HEAD returns the same status and headers as GET for
   health/static routes, with no response body.

Verification:

- `curl -I /` returns 200 for web root.
- Diagnostics show actual bound port from the running server.
- UI labels map cleanly to backend states.

### Phase 5 - Validate Steam Deck audio path before broad code changes

Objective: prove whether the real PipeWire graph works on Steam Deck before
optimizing UI around it.

Tasks:

1. Run `scripts/poc_steamdeck_audio.sh` on Steam Deck Desktop Mode.
2. Capture:
   - `pactl info`
   - `pactl list sinks short`
   - `pactl list sources short`
   - DeckSoundpad module list
   - whether Discord/Steam Voice sees `DeckSoundpad mic`
   - whether the meter moves for soundboard playback and real mic passthrough
3. If PoC fails, fix `backend/decksoundpad/audio_router.py` against the PoC
   before touching Decky UI.
4. Confirm exactly which Pulse-compatible modules are available through
   `pipewire-pulse`:
   - `module-null-sink`
   - `module-remap-source`
   - `module-virtual-source`
   - `module-loopback`
5. If `module-remap-source` fails but `module-virtual-source` works, make the
   fallback explicit in diagnostics and logs.
6. If both Pulse-compatible source modules are unreliable on Steam Deck, spike a
   native PipeWire loopback implementation using `libpipewire-module-loopback`
   or `pw-loopback` before changing the product UI.
7. If PoC passes, add daemon-level integration checks around the same pactl
   module sequence.
8. Refactor `AudioRouter` command execution to follow reference-plugin lessons:
   - use a Decky-safe subprocess env with current UID-derived
     `XDG_RUNTIME_DIR`
   - prefer list arguments over shell strings
   - prefer JSON output where `pactl -f json` is available
   - keep text parsers as compatibility fallback
   - log command stderr and missing command cases in diagnostics
9. Add explicit source/module registration waits after each `load-module`, as
   Virtual Surround Sound does for sinks.

Verification:

- `DeckSoundpad mic` appears in `pactl list sources short`.
- Voice app input meter reacts to sample playback.
- Repair is idempotent: repeated repair does not duplicate modules.
- Reset unloads only DeckSoundpad-created modules.

### Phase 6 - Release readiness checks

Objective: package only when the full app path is reproducible.

Tasks:

1. Add a release smoke command that runs:
   - Python tests
   - `corepack pnpm run build`
   - package script
   - ZIP contents check for `main.py`, `plugin.json`, `dist/index.js`,
     `web/dist/index.html`, backend package, defaults, and docs
2. Document generated artifacts and whether `out/` should be ignored or kept.
3. Decide whether `.tmp-run/` and `out/` should be in `.gitignore`.
4. Keep the Decky `root` flag absent unless a Steam Deck verification note
   documents why root became necessary.

Verification:

- One command proves the ZIP is installable enough for Decky developer tools.
- Generated runtime/build output is not accidentally committed unless intended.

## Recommended Implementation Order

1. Phase 1: simulation URL/port reliability.
2. Phase 2: repair readiness UX.
3. Phase 3: auth/smoke contract cleanup.
4. Phase 4: HEAD and diagnostics clarity.
5. Phase 5: real Steam Deck audio PoC.
6. Phase 6: release checks.

This order fixes the feedback loop first. Without a trustworthy simulation and
smoke path, later audio and UI changes will be hard to verify.
