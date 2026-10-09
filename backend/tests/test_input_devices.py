from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad import input_devices  # noqa: E402
from decksoundpad.input_devices import (  # noqa: E402
    BTN_DPAD_RIGHT,
    BTN_EAST,
    BTN_GRIPL2,
    BTN_GRIPR,
    BTN_GRIPR2,
    BTN_SOUTH,
    BTN_TL,
    BTN_TR,
    BTN_X,
    BTN_Y,
    EV_KEY,
    INPUT_EVENT_STRUCT,
    REPLAY_LAST_SOUND,
    STEAM_DECK_HID_DECK_STATE_TYPE,
    STEAM_DECK_HID_REPORT_VERSION,
    STEAM_DECK_LBUTTON_A,
    STEAM_DECK_LBUTTON_B,
    STEAM_DECK_LBUTTON_DPAD_UP,
    STEAM_DECK_LBUTTON_X,
    STEAM_DECK_LBUTTON_Y,
    STEAM_DECK_REAR_BUTTON_MASKS,
    TOGGLE_OVERLAY,
    classify_overlay_key_press,
    classify_steam_deck_hid_press,
    dominant_steam_deck_stick_direction,
    parse_steam_deck_hid_report,
    read_key_presses,
    read_ready_devices,
)


def input_event(event_type: int, code: int, value: int) -> bytes:
    return INPUT_EVENT_STRUCT.pack(0, 0, event_type, code, value)


class InputDevicesTests(unittest.TestCase):
    def test_steam_deck_hid_report_parses_stick_axes(self) -> None:
        data = bytearray(64)
        struct.pack_into(
            "<HBB",
            data,
            0,
            STEAM_DECK_HID_REPORT_VERSION,
            STEAM_DECK_HID_DECK_STATE_TYPE,
            56,
        )
        struct.pack_into("<II", data, 8, STEAM_DECK_LBUTTON_A, 0)
        struct.pack_into("<hhhh", data, 48, 16000, -17000, -18000, 500)

        report = parse_steam_deck_hid_report(bytes(data))

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["buttons_l"], 0x80)
        self.assertEqual(report["left_stick_x"], 16000)
        self.assertEqual(report["left_stick_y"], 17000)
        self.assertEqual(report["right_stick_x"], -18000)
        self.assertEqual(report["right_stick_y"], -500)
        self.assertEqual(dominant_steam_deck_stick_direction(report), "left")

    def test_overlay_hotkey_button_mappings_cover_all_rear_buttons(self) -> None:
        self.assertEqual(
            input_devices.STEAM_DECK_REAR_BUTTON_MASKS,
            {
                "l4": 1 << 41,
                "l5": 1 << 15,
                "r4": 1 << 42,
                "r5": 1 << 16,
            },
        )
        self.assertEqual(
            input_devices.overlay_hotkey_event_codes("l4"), frozenset({0x224})
        )
        self.assertEqual(
            input_devices.overlay_hotkey_event_codes("l5"), frozenset({0x226})
        )
        self.assertEqual(
            input_devices.overlay_hotkey_event_codes("r4"), frozenset({0x225})
        )
        self.assertEqual(
            input_devices.overlay_hotkey_event_codes("r5"), frozenset({0x227})
        )
        self.assertEqual(
            input_devices.EVDEV_OVERLAY_ACTIONS,
            {
                0x130: "play",
                0x133: "play_stay",
                0x134: "stop",
                0x131: "hide",
                0x220: "up",
                0x221: "down",
                0x222: "left",
                0x223: "right",
                0x136: "page_prev",
                0x137: "page_next",
            },
        )

    def test_automatic_l5_preserves_legacy_event_code_aliases(self) -> None:
        codes = input_devices.overlay_hotkey_event_codes("l5", include_legacy_l5=True)

        self.assertIn(0x138, codes)  # BTN_TL2
        self.assertIn(0x224, codes)  # BTN_GRIPL
        self.assertIn(0x226, codes)  # BTN_GRIPL2
        self.assertIn(0x2C0, codes)  # BTN_TRIGGER_HAPPY1
        self.assertIn(0x2E7, codes)  # BTN_TRIGGER_HAPPY40

    def test_input_device_relevance_requires_controller_and_hotkey_capabilities(
        self,
    ) -> None:
        capabilities = frozenset({0x130, 0x226})

        self.assertTrue(
            input_devices.is_overlay_input_device_relevant(
                "Xbox Elite Wireless Controller",
                capabilities,
            )
        )
        self.assertFalse(
            input_devices.is_overlay_input_device_relevant(
                "Gaming Keyboard",
                capabilities,
            )
        )
        self.assertFalse(
            input_devices.is_overlay_input_device_relevant(
                "Pretend Controller",
                frozenset({0x130}),
            )
        )

    def test_input_device_selector_is_stable_across_event_path_changes(self) -> None:
        first = input_devices.make_input_device_selector(
            "Xbox Wireless Controller",
            "usb-0000:00:14.0-2/input0",
            "controller-serial",
        )
        second = input_devices.make_input_device_selector(
            "Xbox Wireless Controller",
            "usb-0000:00:14.0-2/input0",
            "controller-serial",
        )
        other = input_devices.make_input_device_selector(
            "Xbox Wireless Controller",
            "usb-0000:00:14.0-3/input0",
            "controller-serial",
        )

        self.assertEqual(first, second)
        self.assertRegex(first or "", r"^evdev:[0-9a-f]{16}$")
        self.assertNotEqual(first, other)

    def test_input_device_without_stable_kernel_identity_is_not_selectable(
        self,
    ) -> None:
        selector = input_devices.make_input_device_selector(
            "Generic Controller",
            "",
            "",
        )

        self.assertIsNone(selector)

    def test_filter_overlay_input_devices_honors_explicit_selection(self) -> None:
        first = {
            "id": "evdev:0000000000000001",
            "name": "First",
            "path": "/dev/input/event4",
        }
        second = {
            "id": "evdev:0000000000000002",
            "name": "Second",
            "path": "/dev/input/event7",
        }
        devices = [first, second]

        self.assertEqual(
            input_devices.filter_overlay_input_devices(devices, "auto"), devices
        )
        self.assertEqual(
            input_devices.filter_overlay_input_devices(devices, second["id"]),
            [second],
        )
        self.assertEqual(
            input_devices.filter_overlay_input_devices(
                devices, "evdev:ffffffffffffffff"
            ),
            [],
        )

    def test_duplicate_event_nodes_for_one_controller_are_collapsed(self) -> None:
        devices = [
            {
                "id": "evdev:0000000000000001",
                "name": "Controller",
                "path": "/dev/input/event4",
                "label": "Controller (event4)",
            },
            {
                "id": "evdev:0000000000000001",
                "name": "Controller",
                "path": "/dev/input/event5",
                "label": "Controller (event5)",
            },
        ]

        self.assertEqual(
            input_devices.deduplicate_overlay_input_devices(devices),
            [devices[0]],
        )

    def test_key_press_classification_routes_hotkey_actions_and_replay(self) -> None:
        def classify(code: int, button: str = "l5", legacy: bool = False) -> str | None:
            return classify_overlay_key_press(code, button, include_legacy_l5=legacy)

        self.assertEqual(classify(BTN_GRIPL2), TOGGLE_OVERLAY)
        self.assertEqual(
            classify(0x138, legacy=True), TOGGLE_OVERLAY
        )  # legacy BTN_TL2 alias
        self.assertIsNone(classify(0x138))
        self.assertEqual(classify(BTN_SOUTH), "play")
        self.assertEqual(classify(BTN_DPAD_RIGHT), "right")
        self.assertEqual(classify(BTN_GRIPR2), REPLAY_LAST_SOUND)
        self.assertEqual(classify(BTN_GRIPR2, "r5"), TOGGLE_OVERLAY)
        self.assertEqual(classify(BTN_GRIPR, "r4"), TOGGLE_OVERLAY)
        self.assertIsNone(classify(BTN_GRIPR))

    def test_face_and_shoulder_buttons_map_to_overlay_actions(self) -> None:
        def classify(code: int) -> str | None:
            return classify_overlay_key_press(code, "l5", include_legacy_l5=False)

        self.assertEqual(classify(BTN_X), "play_stay")
        self.assertEqual(classify(BTN_Y), "stop")
        self.assertEqual(classify(BTN_EAST), "hide")
        self.assertEqual(classify(BTN_TL), "page_prev")
        self.assertEqual(classify(BTN_TR), "page_next")
        self.assertEqual(
            classify_steam_deck_hid_press(STEAM_DECK_LBUTTON_X, "l5"), "play_stay"
        )
        self.assertEqual(
            classify_steam_deck_hid_press(STEAM_DECK_LBUTTON_Y, "l5"), "stop"
        )
        self.assertEqual(
            classify_steam_deck_hid_press(STEAM_DECK_LBUTTON_B, "l5"), "hide"
        )
        # A wins when pressed together with another face button.
        self.assertEqual(
            classify_steam_deck_hid_press(
                STEAM_DECK_LBUTTON_A | STEAM_DECK_LBUTTON_B, "l5"
            ),
            "play",
        )

    def test_hid_press_classification_prefers_hotkey_then_replay_then_actions(
        self,
    ) -> None:
        l5 = STEAM_DECK_REAR_BUTTON_MASKS["l5"]
        r5 = STEAM_DECK_REAR_BUTTON_MASKS["r5"]

        self.assertEqual(
            classify_steam_deck_hid_press(l5 | STEAM_DECK_LBUTTON_A, "l5"),
            TOGGLE_OVERLAY,
        )
        self.assertEqual(
            classify_steam_deck_hid_press(r5 | STEAM_DECK_LBUTTON_A, "l5"),
            REPLAY_LAST_SOUND,
        )
        self.assertEqual(classify_steam_deck_hid_press(r5, "r5"), TOGGLE_OVERLAY)
        self.assertEqual(
            classify_steam_deck_hid_press(
                STEAM_DECK_LBUTTON_A | STEAM_DECK_LBUTTON_DPAD_UP, "l5"
            ),
            "play",
        )
        self.assertEqual(
            classify_steam_deck_hid_press(STEAM_DECK_LBUTTON_DPAD_UP, "l5"), "up"
        )
        self.assertIsNone(classify_steam_deck_hid_press(1 << 60, "l5"))

    def test_read_key_presses_yields_only_key_down_events(self) -> None:
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        with os.fdopen(read_fd, "rb", buffering=0) as reader:
            os.write(
                write_fd,
                input_event(EV_KEY, BTN_SOUTH, 1)
                + input_event(EV_KEY, BTN_SOUTH, 0)
                + input_event(0x03, 0x00, 1)  # EV_ABS motion
                + input_event(EV_KEY, BTN_GRIPL2, 1),
            )
            os.close(write_fd)
            presses = list(
                read_key_presses([("/dev/input/event9", reader)], timeout=0.1)
            )

        self.assertEqual(
            presses,
            [("/dev/input/event9", BTN_SOUTH), ("/dev/input/event9", BTN_GRIPL2)],
        )

    def test_discover_overlay_input_devices_filters_sorts_and_deduplicates(
        self,
    ) -> None:
        gamepad_keys = {BTN_SOUTH, BTN_GRIPL2}
        fake_devices = {
            "event2": ("Steam Deck", "usb-1/input0", "", gamepad_keys),
            "event0": ("AT Keyboard", "isa0060/serio0", "", gamepad_keys),
            "event1": ("Xbox Wireless Controller", "bt-1", "serial", gamepad_keys),
            "event3": ("Pretend Controller", "usb-2", "", {BTN_SOUTH}),
            "event5": ("Steam Deck", "usb-1/input0", "", gamepad_keys),
        }
        fd_names: dict[int, str] = {}

        def fake_ioctl(fd: int, request: int, buffer: bytearray, _mutate: bool) -> int:
            name, phys, uniq, keys = fake_devices[fd_names[fd]]
            number = request & 0xFF
            if number == input_devices.EVIOCGBIT_BASE + EV_KEY:
                for code in keys:
                    buffer[code // 8] |= 1 << (code % 8)
                return 0
            value = {
                input_devices.EVIOCGNAME: name,
                input_devices.EVIOCGPHYS: phys,
                input_devices.EVIOCGUNIQ: uniq,
            }[number].encode()
            buffer[: len(value)] = value
            return 0

        real_open = Path.open

        def tracking_open(path: Path, *args: object, **kwargs: object) -> object:
            handle = real_open(path, *args, **kwargs)
            fd_names[handle.fileno()] = path.name
            return handle

        with tempfile.TemporaryDirectory() as tmp:
            for event_name in fake_devices:
                (Path(tmp) / event_name).write_bytes(b"")
            with (
                patch.object(input_devices, "fcntl", MagicMock(ioctl=fake_ioctl)),
                patch.object(Path, "open", tracking_open),
            ):
                devices = input_devices.discover_overlay_input_devices(Path(tmp))

        self.assertEqual(
            [(device["name"], Path(device["path"]).name) for device in devices],
            [("Steam Deck", "event2"), ("Xbox Wireless Controller", "event1")],
        )
        self.assertTrue(all(device["id"].startswith("evdev:") for device in devices))

    def test_open_device_paths_reports_failures_and_keeps_openable_devices(
        self,
    ) -> None:
        errors: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            present = Path(tmp) / "hidraw0"
            present.write_bytes(b"")
            missing = Path(tmp) / "hidraw1"
            handles = input_devices.open_device_paths(
                [present, missing], lambda path, _exc: errors.append(path)
            )
            input_devices.close_device_handles(handles)

        self.assertEqual([path for path, _handle in handles], [str(present)])
        self.assertEqual(errors, [str(missing)])

    def test_read_ready_devices_drains_until_would_block(self) -> None:
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as reader:
                os.write(write_fd, b"a" * 10)
                chunks = list(
                    read_ready_devices([("/dev/hidraw0", reader)], size=4, timeout=0.1)
                )
        finally:
            os.close(write_fd)

        self.assertEqual(
            chunks,
            [
                ("/dev/hidraw0", b"aaaa"),
                ("/dev/hidraw0", b"aaaa"),
                ("/dev/hidraw0", b"aa"),
            ],
        )

    def test_read_ready_devices_returns_nothing_when_idle(self) -> None:
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as reader:
                chunks = list(
                    read_ready_devices([("/dev/hidraw0", reader)], size=4, timeout=0.01)
                )
        finally:
            os.close(write_fd)

        self.assertEqual(chunks, [])

    def test_deduplicate_keeps_devices_without_selector(self) -> None:
        devices = [
            {"id": "", "name": "A", "path": "/dev/input/event1"},
            {"id": "", "name": "B", "path": "/dev/input/event2"},
        ]

        self.assertEqual(
            input_devices.deduplicate_overlay_input_devices(devices), devices
        )

    def test_hidraw_filter_keeps_valve_and_unknown_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sysfs = Path(tmp)
            for name, hid_id in (
                ("hidraw0", "0003:000028DE:00001205"),  # Steam Deck controller
                ("hidraw1", "0003:0000054C:00000CE6"),  # DualSense
            ):
                device = sysfs / name / "device"
                device.mkdir(parents=True)
                (device / "uevent").write_text(
                    f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=controller\n",
                    encoding="utf-8",
                )

            self.assertTrue(input_devices.is_valve_hidraw_device("/dev/hidraw0", sysfs))
            self.assertFalse(
                input_devices.is_valve_hidraw_device("/dev/hidraw1", sysfs)
            )
            self.assertTrue(input_devices.is_valve_hidraw_device("/dev/hidraw7", sysfs))


if __name__ == "__main__":
    unittest.main()
