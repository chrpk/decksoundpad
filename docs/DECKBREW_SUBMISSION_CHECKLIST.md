# Deckbrew Submission Checklist

Source of truth rechecked on 2026-07-09:
https://wiki.deckbrew.xyz/en/plugin-dev/submitting-plugins

This checklist records DeckSoundpad-specific answers for a Decky Plugin
Database submission. Keep it current with the release candidate and link it
from the submission pull request.
Concrete submission evidence should be recorded in
`docs/DECKBREW_SUBMISSION_EVIDENCE.md` or in an equivalent linked release
issue.

## Local Compliance

| Requirement | DeckSoundpad status | Evidence |
| --- | --- | --- |
| Public, open, inspectable repository | Blocked until the final GitHub repository is public | `docs/PUBLICATION_RUNBOOK.md` and `scripts/validate_publication_readiness.sh` require final repository evidence. |
| License file present | Yes | `LICENSE` contains the MIT license. |
| No closed-source or black-box plugin code | Yes for the current checkout | `corepack pnpm run validate:deckbrew` rejects tracked opaque binary archives, executable blobs, WebAssembly, source maps, and minified JS/CSS. |
| No LLM-based code or LLM-focused runtime behavior | Blocked until maintainer provenance evidence exists | Runtime source and metadata are checked for LLM provider/model terms by `corepack pnpm run validate:deckbrew`. The Deckbrew code-provenance rule cannot be proven from repository files alone; final submission requires maintainer evidence that the submitted commit satisfies that rule. |
| No financial transaction or paid-feature flow | Yes | Runtime source and metadata are checked for payment, subscription, donation, and license-key signals. |
| No keyshop links or piracy-adjacent promotions | Yes | Repository URLs are checked for common keyshop domains by `corepack pnpm run validate:deckbrew`. |
| Tested on real Steam Deck hardware running SteamOS | Blocked until release-candidate hardware validation is complete | `docs/HARDWARE_VALIDATION.md`, `docs/STEAMDECK_AUDIO_POC.md`, and `docs/EXTERNAL_OVERLAY_POC.md` capture the required SteamOS evidence. |
| Beta/Preview testing when required | Not currently expected | Re-evaluate if the release depends on a SteamOS Beta/Preview-only Decky or OS behavior. |
| Decky Store image for plugin-index listing | Blocked until public release media exists | `DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1` makes release validation require an HTTPS PNG `plugin.json` `publish.image`. |

## Backend Checklist Answers

| Deckbrew backend question | Answer | Notes |
| --- | --- | --- |
| Does the plugin use a custom backend not using Python? | No | The Decky backend entry point is `main.py`, and backend code lives under `backend/decksoundpad/*.py`. |
| Does the plugin use a tool or software from a third-party FOSS project that does not have its dependencies statically linked? | Yes | DeckSoundpad calls SteamOS/PipeWire/PulseAudio tools such as `pactl` and `pw-play` when available, and may use local playback tools such as `ffmpeg` or `mpv`. These tools are not bundled in the plugin ZIP. |
| Does the plugin use a custom binary that has all of its dependencies statically linked? | No | No custom binary is currently tracked or packaged. |

## Final Submission Steps

1. Publish the final repository and confirm it is publicly visible.
2. Complete the real Steam Deck hardware validation docs for the release
   candidate.
3. Add release screenshots or demo media and set `plugin.json`
   `publish.image` to an HTTPS PNG URL.
4. Record maintainer evidence that the submitted commit satisfies the Deckbrew
   LLM/code-provenance rule.
5. Fill `docs/DECKBREW_SUBMISSION_EVIDENCE.md` with the final public
   repository, submitted commit, hardware validation, release artifact, and
   database pull request links.
6. Run local gates:

   ```bash
   corepack pnpm run validate:deckbrew
   DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1 corepack pnpm run validate:release
   ```

7. Run publication readiness with external evidence:

   ```bash
   DECKSOUNDPAD_REQUIRE_DECKBREW_SUBMISSION=1 corepack pnpm run validate:publication
   ```

8. Fork the Decky Plugin Database, add this public repository as a submodule
   under `plugins/`, and open the submission pull request with links to the
   hardware validation evidence, release artifact, checksum, and this checklist.
