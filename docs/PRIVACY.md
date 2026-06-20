# Privacy And Local Data

DeckSoundpad is designed as a local Decky Loader plugin. It should not expose a
LAN API, send telemetry, upload sound files, or contact third-party services as
part of normal playback, library scanning, audio routing, or overlay use.

## Local Files Read

DeckSoundpad reads:

- configured sound library directories, defaulting to `~/Music/DeckSoundpad`;
- plugin configuration in Decky-managed settings paths;
- local audio device and PipeWire/PulseAudio state;
- local input devices needed for overlay and hotkey behavior.

Sound files remain on the device. The plugin scans file names, paths, sizes,
extensions, and metadata needed to present and play the local library.

## Local Files Written

DeckSoundpad writes:

- user configuration and migration state;
- sound-library cache data;
- PipeWire/PulseAudio module state used for repair and cleanup;
- logs under the plugin log directory;
- mirrored support logs under `~/Public/DeckSoundpad/logs/`.

The mirrored public logs are intended to make support collection easier on
Steam Deck, but they can contain local usernames, filesystem paths, audio device
names, sound filenames, process errors, and Decky runtime paths.

## What Not To Share Publicly

Before posting an issue or discussion, redact:

- local usernames and home-directory paths;
- private sound filenames or library paths;
- audio device names that identify personal hardware;
- private voice chat, game, or account context;
- tokens, webhook URLs, private repository URLs, or service credentials.

Do not upload sound files or voice recordings unless a maintainer explicitly
asks for a minimal test asset and you have the right to share it.

## Network Expectations

Normal DeckSoundpad behavior should not require network access. Do not add a
LAN HTTP API, telemetry, remote crash reporting, or network update checks
without a separate design review and documentation update.

## Security Reports

Do not disclose exploit details publicly. Follow `SECURITY.md` for private
vulnerability reporting expectations.
