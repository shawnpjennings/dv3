"""Right-side tool panel for the DV3 animation editor.

Renders tool buttons, sliders, and a file-property display section.  Every
interaction returns an action dict (or ``None``) so the main loop can dispatch
operations without the panel knowing about file I/O.
"""

from __future__ import annotations

import logging
from typing import Optional

import pygame

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme colours
# ---------------------------------------------------------------------------

COL_PANEL_BG = (0x1E, 0x1E, 0x2A)  # slightly blue-tinted to distinguish from gallery
COL_SECTION_BG = (0x24, 0x24, 0x30)
COL_BTN = (0x33, 0x33, 0x33)
COL_BTN_HOVER = (0x44, 0x44, 0x44)
COL_BTN_ACTIVE = (0x4A, 0x9E, 0xFF)
COL_ACCENT = (0x4A, 0x9E, 0xFF)
COL_TEXT = (0xE0, 0xE0, 0xE0)
COL_TEXT_DIM = (0x88, 0x88, 0x88)
COL_SLIDER_BG = (0x3A, 0x3A, 0x3A)
COL_SLIDER_FILL = (0x4A, 0x9E, 0xFF)
COL_SLIDER_KNOB = (0xE0, 0xE0, 0xE0)
COL_DIVIDER = (0x4A, 0x4A, 0x55)  # visible divider line

# Layout
MARGIN = 12
BTN_H = 30
BTN_GAP = 6
SLIDER_H = 20
SLIDER_KNOB_R = 7
SECTION_PAD = 10


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------

class _Button:
    """A dark-themed button with hover/active states."""

    __slots__ = ("rect", "label", "shortcut", "action", "hovered", "active")

    def __init__(
        self,
        rect: pygame.Rect,
        label: str,
        shortcut: str,
        action: str,
    ) -> None:
        self.rect = rect
        self.label = label
        self.shortcut = shortcut
        self.action = action
        self.hovered = False
        self.active = False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        if self.active:
            col = COL_BTN_ACTIVE
        elif self.hovered:
            col = COL_BTN_HOVER
        else:
            col = COL_BTN
        pygame.draw.rect(surface, col, self.rect, border_radius=4)
        # Border when active
        if self.active:
            pygame.draw.rect(surface, COL_ACCENT, self.rect, 1, border_radius=4)

        text = f"{self.label}  [{self.shortcut}]" if self.shortcut else self.label
        ts = font.render(text, True, COL_TEXT)
        tx = self.rect.x + (self.rect.width - ts.get_width()) // 2
        ty = self.rect.y + (self.rect.height - ts.get_height()) // 2
        surface.blit(ts, (tx, ty))


class _Slider:
    """A horizontal slider with label, min/max, and current value."""

    __slots__ = (
        "rect", "label", "min_val", "max_val", "value", "step",
        "format_str", "dragging", "action",
    )

    def __init__(
        self,
        rect: pygame.Rect,
        label: str,
        min_val: float,
        max_val: float,
        value: float,
        action: str,
        step: float = 1.0,
        format_str: str = "{:.0f}",
    ) -> None:
        self.rect = rect
        self.label = label
        self.min_val = min_val
        self.max_val = max_val
        self.value = value
        self.action = action
        self.step = step
        self.format_str = format_str
        self.dragging = False

    @property
    def _track_rect(self) -> pygame.Rect:
        """Inner track area (excluding label row)."""
        return pygame.Rect(
            self.rect.x, self.rect.y + 16,
            self.rect.width, SLIDER_H,
        )

    def _value_to_x(self, track: pygame.Rect) -> int:
        ratio = (self.value - self.min_val) / max(0.0001, self.max_val - self.min_val)
        return track.x + int(ratio * track.width)

    def _x_to_value(self, x: int, track: pygame.Rect) -> float:
        ratio = max(0.0, min(1.0, (x - track.x) / max(1, track.width)))
        raw = self.min_val + ratio * (self.max_val - self.min_val)
        # Snap to step
        if self.step > 0:
            raw = round(raw / self.step) * self.step
        return max(self.min_val, min(self.max_val, raw))

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        track = self._track_rect

        # Label + value
        val_str = self.format_str.format(self.value)
        label_surf = font.render(f"{self.label}: {val_str}", True, COL_TEXT_DIM)
        surface.blit(label_surf, (self.rect.x, self.rect.y))

        # Track background
        track_inner = pygame.Rect(track.x, track.y + 6, track.width, 6)
        pygame.draw.rect(surface, COL_SLIDER_BG, track_inner, border_radius=3)

        # Filled portion
        knob_x = self._value_to_x(track)
        fill_rect = pygame.Rect(track.x, track.y + 6, knob_x - track.x, 6)
        pygame.draw.rect(surface, COL_SLIDER_FILL, fill_rect, border_radius=3)

        # Knob
        knob_y = track.y + 9
        pygame.draw.circle(surface, COL_SLIDER_KNOB, (knob_x, knob_y), SLIDER_KNOB_R)

    def handle_mouse_down(self, pos: tuple[int, int]) -> bool:
        """Return True if this slider captured the press."""
        track = self._track_rect
        expanded = track.inflate(0, 12)
        if expanded.collidepoint(pos):
            self.dragging = True
            self.value = self._x_to_value(pos[0], track)
            return True
        return False

    def handle_mouse_move(self, pos: tuple[int, int]) -> None:
        if self.dragging:
            track = self._track_rect
            self.value = self._x_to_value(pos[0], track)

    def handle_mouse_up(self) -> None:
        self.dragging = False


# ---------------------------------------------------------------------------
# EditorPanel
# ---------------------------------------------------------------------------

class EditorPanel:
    """Right-side tool panel with buttons, sliders, and property display.

    Args:
        rect: Bounding rectangle on the parent surface.
    """

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect: pygame.Rect = rect

        self._font: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None

        # File info
        self._file_name: str = ""
        self._file_dims: str = ""
        self._file_frames: str = ""
        self._file_size: str = ""
        self._file_format: str = ""

        # Active tool tracking (for toggle states)
        self._active_tool: Optional[str] = None  # "crop" | "fill" | "gradient" | None

        # Build UI elements (positions computed in _layout)
        self._buttons: list[_Button] = []
        self._sliders: dict[str, _Slider] = {}
        self._layout()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        """Compute positions for all buttons and sliders."""
        x = self.rect.x + MARGIN
        w = self.rect.width - MARGIN * 2
        y = self.rect.y + MARGIN

        # ---- section: File Info (height reserved, drawn in render) ----
        self._info_y = y
        y += 100  # reserve space for 5 lines of info

        # ---- section: Tools ----
        y += SECTION_PAD
        self._tools_label_y = y
        y += 20

        btn_defs = [
            ("Crop", "C", "crop"),
            ("Black Fill", "B", "fill"),
            ("Padding", "", "padding"),
            ("Gradient", "G", "gradient_toggle"),
            ("Speed", "", "speed"),
            ("Convert WebP", "", "convert"),
            ("Save", "S", "save"),
        ]
        self._buttons.clear()
        # 2 columns of buttons
        col_w = (w - BTN_GAP) // 2
        for i, (label, shortcut, action) in enumerate(btn_defs):
            col = i % 2
            row = i // 2
            bx = x + col * (col_w + BTN_GAP)
            by = y + row * (BTN_H + BTN_GAP)
            self._buttons.append(
                _Button(pygame.Rect(bx, by, col_w, BTN_H), label, shortcut, action)
            )

        rows_needed = (len(btn_defs) + 1) // 2
        y += rows_needed * (BTN_H + BTN_GAP) + SECTION_PAD

        # ---- section: Sliders ----
        self._sliders_label_y = y
        y += 20
        slider_h_total = 36  # label row + track

        self._sliders["gradient_opacity"] = _Slider(
            pygame.Rect(x, y, w, slider_h_total),
            "Gradient Opacity", 0, 100, 85, "gradient_opacity",
            step=1, format_str="{:.0f}%",
        )
        y += slider_h_total + 8

        self._sliders["gradient_size"] = _Slider(
            pygame.Rect(x, y, w, slider_h_total),
            "Gradient Size", 0, 100, 70, "gradient_size",
            step=1, format_str="{:.0f}%",
        )
        y += slider_h_total + 8

        self._sliders["speed"] = _Slider(
            pygame.Rect(x, y, w, slider_h_total),
            "Speed", 0.25, 4.0, 1.0, "speed",
            step=0.25, format_str="{:.2f}x",
        )
        y += slider_h_total + 8

        self._sliders["padding"] = _Slider(
            pygame.Rect(x, y, w, slider_h_total),
            "Padding", 0, 50, 0, "padding",
            step=1, format_str="{:.0f}px",
        )

    def set_rect(self, rect: pygame.Rect) -> None:
        """Recalculate layout after a resize."""
        self.rect = rect
        self._layout()

    # ------------------------------------------------------------------
    # File info
    # ------------------------------------------------------------------

    def set_file_info(
        self,
        path: str,
        dimensions: tuple[int, int],
        frame_count: int,
        file_size: int,
        fmt: str,
    ) -> None:
        """Update the property display section."""
        from pathlib import Path as _P

        self._file_name = _P(path).name
        w, h = dimensions
        self._file_dims = f"{w} x {h}"
        self._file_frames = str(frame_count)
        if file_size < 1024:
            self._file_size = f"{file_size} B"
        elif file_size < 1024 * 1024:
            self._file_size = f"{file_size / 1024:.1f} KB"
        else:
            self._file_size = f"{file_size / (1024 * 1024):.2f} MB"
        self._file_format = fmt.upper()

    def clear_file_info(self) -> None:
        """Clear the property display (no file selected)."""
        self._file_name = ""
        self._file_dims = ""
        self._file_frames = ""
        self._file_size = ""
        self._file_format = ""
        self._active_tool = None
        for btn in self._buttons:
            btn.active = False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        """Draw the full panel."""
        if self._font is None:
            pygame.font.init()
            self._font = pygame.font.SysFont("consolas,dejavusansmono,monospace", 12)
            self._font_small = pygame.font.SysFont("consolas,dejavusansmono,monospace", 11)

        font = self._font
        font_sm = self._font_small
        assert font is not None and font_sm is not None

        # Panel background
        pygame.draw.rect(surface, COL_PANEL_BG, self.rect)
        # Left edge divider
        pygame.draw.line(
            surface, COL_DIVIDER,
            (self.rect.x, self.rect.y),
            (self.rect.x, self.rect.y + self.rect.height),
        )

        x = self.rect.x + MARGIN

        # ---- File info section ----
        y = self._info_y
        title = font.render("FILE INFO", True, COL_ACCENT)
        surface.blit(title, (x, y))
        y += 18

        info_lines = [
            ("Name", self._file_name or "--"),
            ("Size", self._file_dims or "--"),
            ("Frames", self._file_frames or "--"),
            ("File", self._file_size or "--"),
            ("Format", self._file_format or "--"),
        ]
        for label, val in info_lines:
            ls = font_sm.render(f"{label}:", True, COL_TEXT_DIM)
            vs = font_sm.render(val, True, COL_TEXT)
            surface.blit(ls, (x, y))
            surface.blit(vs, (x + 70, y))
            y += 15

        # ---- Tools section header ----
        tools_title = font.render("TOOLS", True, COL_ACCENT)
        surface.blit(tools_title, (x, self._tools_label_y))

        # ---- Buttons ----
        for btn in self._buttons:
            btn.draw(surface, font_sm)

        # ---- Sliders section header ----
        slider_title = font.render("ADJUSTMENTS", True, COL_ACCENT)
        surface.blit(slider_title, (x, self._sliders_label_y))

        for slider in self._sliders.values():
            slider.draw(surface, font_sm)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> Optional[dict]:
        """Process a pygame event, returning an action dict or None.

        Action dict examples:
            {"action": "crop"}
            {"action": "fill"}
            {"action": "gradient_toggle"}
            {"action": "save"}
            {"action": "convert"}
            {"action": "padding", "params": {"size": 10}}
            {"action": "speed", "params": {"multiplier": 2.0}}
            {"action": "slider_change", "slider": "gradient_opacity", "value": 85}
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if not self.rect.collidepoint(pos):
                return None

            # Check sliders first (they capture drag)
            for name, slider in self._sliders.items():
                if slider.handle_mouse_down(pos):
                    return {
                        "action": "slider_change",
                        "slider": name,
                        "value": slider.value,
                    }

            # Check buttons
            for btn in self._buttons:
                if btn.rect.collidepoint(pos):
                    return self._activate_button(btn)

        elif event.type == pygame.MOUSEMOTION:
            pos = event.pos
            # Button hover
            for btn in self._buttons:
                btn.hovered = btn.rect.collidepoint(pos)
            # Slider drag
            for name, slider in self._sliders.items():
                if slider.dragging:
                    slider.handle_mouse_move(pos)
                    return {
                        "action": "slider_change",
                        "slider": name,
                        "value": slider.value,
                    }

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for slider in self._sliders.values():
                slider.handle_mouse_up()

        return None

    def activate_by_shortcut(self, action: str) -> Optional[dict]:
        """Activate a tool by its action name (called from keyboard shortcuts)."""
        for btn in self._buttons:
            if btn.action == action:
                return self._activate_button(btn)
        return None

    # ------------------------------------------------------------------
    # Slider accessors
    # ------------------------------------------------------------------

    def get_slider_value(self, name: str) -> float:
        """Return the current value of a named slider."""
        slider = self._sliders.get(name)
        return slider.value if slider else 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _activate_button(self, btn: _Button) -> dict:
        """Handle a button press, managing toggle states for tool buttons."""
        toggle_actions = {"crop", "fill", "gradient_toggle"}

        if btn.action in toggle_actions:
            if btn.active:
                # Deactivate
                btn.active = False
                self._active_tool = None
            else:
                # Deactivate other toggle buttons first
                for b in self._buttons:
                    if b.action in toggle_actions:
                        b.active = False
                btn.active = True
                self._active_tool = btn.action
        # Non-toggle buttons just fire
        result: dict = {"action": btn.action}

        # Attach slider params for relevant actions
        if btn.action == "padding":
            result["params"] = {"size": int(self._sliders["padding"].value)}
        elif btn.action == "speed":
            result["params"] = {"multiplier": self._sliders["speed"].value}
        elif btn.action == "gradient_toggle":
            result["params"] = {
                "opacity": int(self._sliders["gradient_opacity"].value),
                "size": int(self._sliders["gradient_size"].value),
            }
        elif btn.action == "save":
            result["params"] = {
                "speed": self._sliders["speed"].value,
                "padding": int(self._sliders["padding"].value),
                "gradient_opacity": int(self._sliders["gradient_opacity"].value),
                "gradient_size": int(self._sliders["gradient_size"].value),
            }

        return result

    def deactivate_tools(self) -> None:
        """Deactivate all toggle-able tool buttons."""
        self._active_tool = None
        for btn in self._buttons:
            if btn.action in {"crop", "fill", "gradient_toggle"}:
                btn.active = False
