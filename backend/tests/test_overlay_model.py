from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.overlay_layout import (  # noqa: E402
    GRID_COLUMNS,
    GRID_GAP,
    HIT_GRID,
    HIT_OUTSIDE,
    HIT_TAB,
    HIT_TILE,
    SOUNDS_PER_PAGE,
    Rect,
    hit_test,
    overlay_layout,
    visible_tab_range,
)
from decksoundpad.overlay_model import (  # noqa: E402
    RECENT_STORE_LIMIT,
    RECENT_TAB_LIMIT,
    build_tabs,
    display_library_dir,
    flip_page,
    load_recent_ids,
    move_horizontal,
    move_vertical,
    push_recent,
    save_recent_ids,
    summarize_mic_status,
)


def sounds(
    count: int, category: str = "uncategorized", prefix: str = "sound"
) -> list[dict[str, object]]:
    return [
        {
            "id": f"{prefix}-{index}",
            "display_name": f"{prefix} {index}",
            "category": category,
        }
        for index in range(count)
    ]


def ready_status(**audio_overrides: object) -> dict[str, object]:
    audio: dict[str, object] = {
        "state": "ready",
        "pactl_available": True,
        "pipewire_available": True,
        "sink_exists": True,
        "virtual_mic_exists": True,
        "loopback_exists": True,
        "selected_real_mic": "alsa_input.mic",
    }
    audio.update(audio_overrides)
    return {"backend_running": True, "audio": audio}


class OverlayTabsTests(unittest.TestCase):
    def test_loose_files_only_show_one_all_sounds_tab(self) -> None:
        tabs = build_tabs(sounds(3), [])

        self.assertEqual(
            [(tab.key, tab.label, len(tab.sounds)) for tab in tabs],
            [("all", "All sounds", 3)],
        )

    def test_single_folder_still_shows_one_tab(self) -> None:
        tabs = build_tabs(sounds(2, "memes"), [])

        self.assertEqual([tab.key for tab in tabs], ["all"])

    def test_empty_library_keeps_an_empty_tab(self) -> None:
        tabs = build_tabs([], ["gone"])

        self.assertEqual([(tab.key, len(tab.sounds)) for tab in tabs], [("all", 0)])
        self.assertEqual(tabs[0].page_count, 1)

    def test_folders_get_tabs_with_loose_files_last(self) -> None:
        library = (
            sounds(1, "uncategorized", "loose")
            + sounds(2, "memes", "meme")
            + sounds(1, "music", "song")
        )
        tabs = build_tabs(library, [])

        self.assertEqual([tab.label for tab in tabs], ["memes", "music", "Other"])
        self.assertEqual([len(tab.sounds) for tab in tabs], [2, 1, 1])

    def test_recent_tab_comes_first_and_skips_missing_sounds(self) -> None:
        library = sounds(4)
        tabs = build_tabs(library, ["sound-2", "deleted", "sound-0"])

        self.assertEqual(tabs[0].key, "recent")
        self.assertEqual(
            [sound["id"] for sound in tabs[0].sounds], ["sound-2", "sound-0"]
        )

    def test_recent_tab_is_capped(self) -> None:
        library = sounds(30)
        tabs = build_tabs(library, [f"sound-{index}" for index in range(30)])

        self.assertEqual(len(tabs[0].sounds), RECENT_TAB_LIMIT)

    def test_page_count_rounds_up(self) -> None:
        tab = build_tabs(sounds(SOUNDS_PER_PAGE + 1), [])[0]

        self.assertEqual(tab.page_count, 2)


class OverlayNavigationTests(unittest.TestCase):
    def test_vertical_navigation_uses_grid_columns(self) -> None:
        self.assertEqual(move_vertical(1, 18, 1), 1 + GRID_COLUMNS)
        self.assertEqual(move_vertical(1 + GRID_COLUMNS, 18, -1), 1)
        # The next row is partial, so down lands on its last sound.
        self.assertEqual(move_vertical(GRID_COLUMNS * 2 + GRID_COLUMNS - 1, 18, 1), 17)
        # Down from the last row wraps to the top of the same column.
        self.assertEqual(move_vertical(16, 18, 1), 1)
        # Up from the top row wraps to the same column on the last row.
        self.assertEqual(move_vertical(2, 18, -1), 17)
        self.assertEqual(move_vertical(1, 18, -1), 16)

    def test_vertical_navigation_flows_onto_the_next_page(self) -> None:
        last_row_start = SOUNDS_PER_PAGE - GRID_COLUMNS

        self.assertEqual(move_vertical(last_row_start + 2, 50, 1), SOUNDS_PER_PAGE + 2)

    def test_horizontal_navigation_flows_across_rows_and_pages(self) -> None:
        self.assertEqual(move_horizontal(GRID_COLUMNS - 1, 50, 1), GRID_COLUMNS)
        self.assertEqual(move_horizontal(SOUNDS_PER_PAGE - 1, 50, 1), SOUNDS_PER_PAGE)
        self.assertEqual(move_horizontal(49, 50, 1), 0)
        self.assertEqual(move_horizontal(0, 50, -1), 49)
        self.assertEqual(move_horizontal(3, 0, 1), 0)

    def test_page_flip_keeps_grid_position_and_crosses_tabs(self) -> None:
        tabs = build_tabs(
            sounds(2, "a", "a") + sounds(50, "b", "b") + sounds(3, "c", "c"), []
        )

        # From tab b page 1, tile 7, R1 goes to page 2 and keeps tile 7.
        self.assertEqual(flip_page(tabs, 1, 7, 1), (1, SOUNDS_PER_PAGE + 7))
        # Tile 20 does not exist on the short page 2, so the cursor clamps.
        self.assertEqual(flip_page(tabs, 1, 20, 1), (1, 49))
        # R1 on the last page moves into the next tab.
        self.assertEqual(flip_page(tabs, 1, SOUNDS_PER_PAGE + 1, 1), (2, 1))
        # L1 on the first page goes to the previous tab's last page.
        self.assertEqual(flip_page(tabs, 2, 0, -1), (1, SOUNDS_PER_PAGE))
        # Both ends wrap.
        self.assertEqual(flip_page(tabs, 0, 1, -1), (2, 1))
        self.assertEqual(flip_page(tabs, 2, 2, 1), (0, 1))


class RecentSoundsTests(unittest.TestCase):
    def test_push_recent_moves_sound_to_front_without_duplicates(self) -> None:
        self.assertEqual(push_recent(["a", "b", "c"], "b"), ["b", "a", "c"])
        self.assertEqual(
            len(push_recent([str(index) for index in range(40)], "new")),
            RECENT_STORE_LIMIT,
        )

    def test_recent_ids_round_trip_and_tolerate_bad_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "overlay_recent.json"
            self.assertEqual(load_recent_ids(path), [])

            save_recent_ids(path, ["a", "b"])
            self.assertEqual(load_recent_ids(path), ["a", "b"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_recent_ids(path), [])

            path.write_text('{"sound_ids": ["a", 3, null]}', encoding="utf-8")
            self.assertEqual(load_recent_ids(path), ["a"])


class MicStatusTests(unittest.TestCase):
    def test_ready_route_reports_ok(self) -> None:
        self.assertEqual(
            summarize_mic_status(ready_status()), {"tone": "ok", "label": "Mic ready"}
        )

    def test_offline_and_missing_status_report_errors(self) -> None:
        self.assertEqual(summarize_mic_status(None)["tone"], "error")
        self.assertEqual(
            summarize_mic_status({"backend_running": False})["label"], "Audio offline"
        )

    def test_restart_and_pending_states_warn(self) -> None:
        self.assertEqual(
            summarize_mic_status(ready_status(state="repairing"))["label"],
            "Audio restarting",
        )
        self.assertEqual(
            summarize_mic_status(ready_status(state="pending"))["label"],
            "Checking audio",
        )

    def test_missing_virtual_mic_needs_a_restart(self) -> None:
        mic = summarize_mic_status(
            ready_status(state="needs_repair", virtual_mic_exists=False)
        )

        self.assertEqual(mic["tone"], "error")
        self.assertIn("restart in Decky", mic["label"])

    def test_broken_loopback_warns(self) -> None:
        mic = summarize_mic_status(
            ready_status(state="needs_repair", loopback_exists=False)
        )

        self.assertEqual(mic, {"tone": "warn", "label": "Needs restart in Decky"})

    def test_no_real_mic_still_plays_sounds(self) -> None:
        mic = summarize_mic_status(
            ready_status(state="needs_repair", selected_real_mic=None)
        )

        self.assertEqual(mic["tone"], "ok")

    def test_pipewire_unavailable(self) -> None:
        mic = summarize_mic_status(ready_status(state="error", pactl_available=False))

        self.assertEqual(mic, {"tone": "error", "label": "PipeWire unavailable"})

    def test_library_dir_is_shown_relative_to_home(self) -> None:
        home = Path("/home/deck")
        status = {"library": {"dirs": ["/home/deck/Music/DeckSoundpad"]}}

        self.assertEqual(display_library_dir(status, home), "~/Music/DeckSoundpad")
        self.assertEqual(
            display_library_dir({"library": {"dirs": ["/run/media/sd/sounds"]}}, home),
            "/run/media/sd/sounds",
        )
        self.assertIsNone(display_library_dir(None, home))


class OverlayLayoutTests(unittest.TestCase):
    def test_grid_fits_inside_the_screen(self) -> None:
        layout = overlay_layout(1280, 800)
        last = layout.tile_rect(SOUNDS_PER_PAGE - 1)

        self.assertAlmostEqual(last.right, layout.grid.right, places=4)
        self.assertAlmostEqual(last.bottom, layout.grid.bottom, places=4)
        self.assertLess(layout.header.bottom, layout.grid.y)
        self.assertLess(layout.grid.bottom, layout.footer.y)

    def test_hit_test_classifies_tiles_gaps_tabs_and_outside(self) -> None:
        layout = overlay_layout(1280, 800)
        tile = layout.tile_rect(6)
        tab = Rect(40, 60, 100, 34)

        self.assertEqual(
            hit_test(layout, tile.x + 5, tile.y + 5, 10, [(tab, 2)]), (HIT_TILE, 6)
        )
        self.assertEqual(
            hit_test(layout, tile.right + GRID_GAP / 2, tile.y + 5, 10),
            (HIT_GRID, None),
        )
        # Tiles beyond the page's sound count are empty grid space.
        self.assertEqual(hit_test(layout, tile.x + 5, tile.y + 5, 3), (HIT_GRID, None))
        self.assertEqual(hit_test(layout, 50, 70, 10, [(tab, 2)]), (HIT_TAB, 2))
        self.assertEqual(hit_test(layout, 5, 790, 10), (HIT_OUTSIDE, None))

    def test_visible_tab_range_keeps_current_tab_in_view(self) -> None:
        self.assertEqual(visible_tab_range([50, 50, 50], 1, 200, 10), (0, 3))
        start, end = visible_tab_range([100] * 10, 8, 330, 10)

        self.assertTrue(start <= 8 < end)
        self.assertEqual(end - start, 3)
        self.assertEqual(visible_tab_range([], 0, 100, 10), (0, 0))


if __name__ == "__main__":
    unittest.main()
