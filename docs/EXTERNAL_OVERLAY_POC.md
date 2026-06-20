# External Overlay PoC

This PoC keeps Decky as the configurator and installer. In-game controls are
owned by backend user-mode input monitors, and rendering is handled by a separate
user-mode GTK/X11 process.

For release candidates, record the full result in
[docs/HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).

## Runtime Flow

1. The backend opens readable `/dev/hidraw*` devices and watches Steam Deck HID
   state reports for L5/A/D-pad/L1/R1.
2. The backend also opens readable `/dev/input/event*` devices as a diagnostic
   fallback for alternate input stacks.
3. A direct L5 press toggles the external overlay through the backend hotkey
   handler in `main.py`.
4. `main.py` starts `backend/decksoundpad/external_overlay.py` as the Steam
   session user with:
   - `GDK_BACKEND=x11`
   - `DISPLAY=:0` when no display is provided
5. The overlay process creates a transparent GTK window and sets:
   - `GAMESCOPE_EXTERNAL_OVERLAY=1`
   - `STEAM_EXTERNAL_OVERLAY=1`
6. Backend HID input handles controls while the overlay is open in-game:
   - `A`: play selected sound
   - D-pad: move selection
   - `L1` / `R1`: page
   - `L5`: close

## Steam Deck Test

Package and install the plugin, then launch a game in Game Mode.

Press L5. Expected result:

- no Decky modal is created;
- a DeckSoundpad grid appears over the game;
- A plays the selected sound and hides the grid.

Useful logs:

- `~/Public/DeckSoundpad/logs/bridge.log`
- `~/Public/DeckSoundpad/logs/external-overlay.log`

For in-game L5, look for `Steam Deck HID state report detected`,
`Steam Deck HID L5 press`, and `L5 direct hotkey handled by backend` entries.

If the overlay process starts but nothing appears, verify that the Game Mode
session exposes an X display and that `GAMESCOPE_EXTERNAL_OVERLAY` is still
accepted by gamescope on the installed SteamOS build.
