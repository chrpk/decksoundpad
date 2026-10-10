"""Layout math and hit testing for the external overlay.

Kept free of GTK and cairo so the bridge and the tests can share the grid
geometry with the renderer in ``external_overlay.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

GRID_COLUMNS = 5
GRID_ROWS = 7
SOUNDS_PER_PAGE = GRID_COLUMNS * GRID_ROWS
GRID_GAP = 10
MIN_PADDING = 18
MAX_PADDING = 32
HEADER_HEIGHT = 108
FOOTER_HEIGHT = 60
TAB_BAR_HEIGHT = 34
TAB_BAR_BOTTOM_MARGIN = 12
GRID_MARGIN = 14

HIT_TAB = "tab"
HIT_TILE = "tile"
HIT_GRID = "grid"
HIT_OUTSIDE = "outside"


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.right and self.y <= py <= self.bottom


@dataclass(frozen=True)
class OverlayLayout:
    width: float
    height: float
    padding: float
    header: Rect
    tab_bar: Rect
    grid: Rect
    footer: Rect
    cell_width: float
    cell_height: float

    def tile_rect(self, index: int) -> Rect:
        row, col = divmod(index, GRID_COLUMNS)
        return Rect(
            self.grid.x + col * (self.cell_width + GRID_GAP),
            self.grid.y + row * (self.cell_height + GRID_GAP),
            self.cell_width,
            self.cell_height,
        )

    def tile_index_at(self, x: float, y: float, tile_count: int) -> int | None:
        for index in range(min(tile_count, SOUNDS_PER_PAGE)):
            if self.tile_rect(index).contains(x, y):
                return index
        return None


def overlay_layout(width: float, height: float) -> OverlayLayout:
    padding = min(MAX_PADDING, max(MIN_PADDING, width * 0.025))
    header_height = min(HEADER_HEIGHT, max(96, height * 0.14))
    footer_height = min(FOOTER_HEIGHT, max(52, height * 0.075))
    content_width = max(1.0, width - padding * 2)
    tab_bar = Rect(
        padding,
        header_height - TAB_BAR_HEIGHT - TAB_BAR_BOTTOM_MARGIN,
        content_width,
        TAB_BAR_HEIGHT,
    )
    grid_top = header_height + GRID_MARGIN
    grid_bottom = height - footer_height - GRID_MARGIN
    grid = Rect(padding, grid_top, content_width, max(1.0, grid_bottom - grid_top))
    return OverlayLayout(
        width=width,
        height=height,
        padding=padding,
        header=Rect(0, 0, width, header_height),
        tab_bar=tab_bar,
        grid=grid,
        footer=Rect(0, height - footer_height, width, footer_height),
        cell_width=max(
            1.0, (grid.width - GRID_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
        ),
        cell_height=max(1.0, (grid.height - GRID_GAP * (GRID_ROWS - 1)) / GRID_ROWS),
    )


def visible_tab_range(
    widths: Sequence[float],
    current: int,
    available: float,
    gap: float,
) -> tuple[int, int]:
    """Return the ``[start, end)`` slice of tabs that fits and keeps ``current`` visible."""

    count = len(widths)
    if count == 0:
        return 0, 0
    if sum(widths) + gap * (count - 1) <= available:
        return 0, count
    current = max(0, min(current, count - 1))
    start, end = current, current + 1
    used = widths[current]
    grew = True
    while grew:
        grew = False
        if end < count and used + gap + widths[end] <= available:
            used += gap + widths[end]
            end += 1
            grew = True
        if start > 0 and used + gap + widths[start - 1] <= available:
            used += gap + widths[start - 1]
            start -= 1
            grew = True
    return start, end


def hit_test(
    layout: OverlayLayout,
    x: float,
    y: float,
    tile_count: int,
    tab_rects: Sequence[tuple[Rect, int]] = (),
) -> tuple[str, int | None]:
    """Classify a touch or click as a tab, a tile, a gap in the grid, or outside."""

    for rect, index in tab_rects:
        if rect.contains(x, y):
            return HIT_TAB, index
    tile = layout.tile_index_at(x, y, tile_count)
    if tile is not None:
        return HIT_TILE, tile
    if layout.grid.contains(x, y):
        # Gaps between tiles are near misses, not a request to close.
        return HIT_GRID, None
    return HIT_OUTSIDE, None
