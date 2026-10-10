# Compatibility

DeckSoundpad is hardware-sensitive because it depends on Decky Loader,
SteamOS audio routing, PipeWire/PulseAudio behavior, and Steam Deck input
devices. This document records what is supported for public releases.

## Release Status

No public release should claim broad compatibility until real Steam Deck
hardware validation is complete for that release candidate.

| Area | Current public-release status |
| --- | --- |
| Steam Deck hardware | Requires release-candidate validation |
| SteamOS version | Minimum supported version not yet established |
| Decky Loader version | Minimum supported version not yet established |
| Audio routing | Requires PipeWire/PulseAudio validation on real hardware |
| Real microphone passthrough | Uses the input device selected in Steam Settings > Audio |
| External overlay | Requires Game Mode validation |
| Non-SteamOS desktop environments | Development/simulation only |

## Required Release Evidence

Before filling in a minimum supported version, complete
`docs/HARDWARE_VALIDATION.md` for the release candidate and record:

- Steam Deck model;
- SteamOS version;
- Decky Loader version;
- plugin version or commit;
- ZIP checksum;
- audio routing result;
- external overlay result;
- No-Root Device Diagnostic result;
- screenshots or demo assets.

## Supported Claims After Validation

After hardware validation passes, update this document with:

- lowest tested SteamOS version;
- lowest tested Decky Loader version;
- tested Steam Deck model;
- known unsupported SteamOS or Decky Loader versions;
- known voice apps tested with `DeckSoundpad mic`;
- known overlay limitations.

## Current Non-Goals

- No support claim for non-Steam Deck Linux desktops.
- No support claim for Windows, macOS, or WSL.
- No requirement to install packages with `pacman`.
- No support for network playback, remote libraries, or LAN control APIs.

Simulation mode remains useful for backend development, but simulation results
do not replace real Steam Deck validation for compatibility claims.
