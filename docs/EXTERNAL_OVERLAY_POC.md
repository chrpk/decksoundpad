# External Overlay PoC

This PoC keeps Decky as the configurator and installer. In-game controls are
owned by backend user-mode input monitors, and rendering is handled by a separate
user-mode GTK/X11 process.

For release candidates, record the full result in
[docs/HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).

## Runtime Flow

1. The backend discovers compatible `/dev/input/event*` controller nodes and
   exposes them to the Decky settings dropdown. The persisted selector is
   `auto` or a stable `evdev:` identity.
2. `Automatic` opens Steam Deck `/dev/hidraw*` state reports plus compatible
   evdev hotkey sources. Explicit selection disables the Steam Deck HID parser
   and reads only the selected controller's normalized evdev events.
3. A direct press of the rear button selected in Decky settings toggles the
   external overlay through the backend hotkey handler in `main.py`. L5 remains
   the default for existing configurations.
4. `main.py` starts `backend/decksoundpad/external_overlay.py` as the Steam
   session user with:
   - `GDK_BACKEND=x11`
   - `DISPLAY=:0` when no display is provided
5. The overlay process creates a transparent GTK window and sets:
   - `GAMESCOPE_EXTERNAL_OVERLAY=1`
   - `STEAM_EXTERNAL_OVERLAY=1`
6. Steam Deck HID or selected-controller evdev input handles controls while the
   overlay is open in-game:
   - `A`: play selected sound
   - D-pad: move selection
   - `L1` / `R1`: page
   - configured rear button: close

## Steam Deck Test

Package and install the plugin, then launch a game in Game Mode.

Choose L4, L5, R4, or R5 under Decky > DeckSoundpad > Settings, then press
that button. Expected result:

- no Decky modal is created;
- a DeckSoundpad grid appears over the game;
- A plays the selected sound and hides the grid.

Useful logs:

- `~/Public/DeckSoundpad/logs/bridge.log`
- `~/Public/DeckSoundpad/logs/external-overlay.log`

For the in-game hotkey, look for `Steam Deck HID state report detected`,
`Steam Deck HID overlay hotkey press`, and `Overlay direct hotkey handled by
backend` entries. Each hotkey log includes the selected button.

If the overlay process starts but nothing appears, verify that the Game Mode
session exposes an X display and that `GAMESCOPE_EXTERNAL_OVERLAY` is still
accepted by gamescope on the installed SteamOS build.
