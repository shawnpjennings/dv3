"""DV3 Animation Editor -- entry point.

A Pygame-based tool for browsing, previewing, and editing animated WebP/GIF
files used by the DV3 visualizer.  Run with::

    python -m editor.main [directory_path]

Layout:
    Left 60% -- scrollable gallery of animated thumbnails
    Right 40% -- editor tools panel (top) + animation preview (bottom)

Keyboard shortcuts:
    Space   Play / Pause animation preview
    C       Crop tool (interactive rectangle)
    B       Black fill tool (watermark removal)
    G       Toggle gradient preview overlay
    S       Save / export current file
    Delete  Remove selected file from gallery
    Escape  Deselect / close active tool
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pygame

from editor.converter import BatchConverter
from editor.editor_panel import EditorPanel
from editor.gallery import Gallery
from editor.gradient_tool import GradientTool
from editor.preview import PreviewPanel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

COL_BG = (0x1A, 0x1A, 0x1A)
COL_ACCENT = (0x4A, 0x9E, 0xFF)
COL_TEXT = (0xE0, 0xE0, 0xE0)
COL_TEXT_DIM = (0x80, 0x80, 0x80)
COL_STATUS_BG = (0x20, 0x20, 0x20)

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
GALLERY_RATIO = 0.60  # left 60%


# ---------------------------------------------------------------------------
# EditorApp
# ---------------------------------------------------------------------------

class EditorApp:
    """Main editor application.

    Args:
        directory: Root directory containing animation files to edit.
    """

    def __init__(self, directory: str = "animations") -> None:
        pygame.init()
        pygame.font.init()

        self._directory = str(Path(directory).resolve())
        self._running = False

        # Window
        self._screen = pygame.display.set_mode(
            (DEFAULT_WIDTH, DEFAULT_HEIGHT), pygame.RESIZABLE
        )
        pygame.display.set_caption("DV3 Animation Editor")

        # Clock
        self._clock = pygame.time.Clock()

        # Layout rects (computed in _layout)
        self._gallery_rect = pygame.Rect(0, 0, 0, 0)
        self._panel_rect = pygame.Rect(0, 0, 0, 0)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)
        self._status_rect = pygame.Rect(0, 0, 0, 0)
        self._layout()

        # Panels
        self._gallery = Gallery(self._gallery_rect, self._directory)
        self._panel = EditorPanel(self._panel_rect)
        self._preview = PreviewPanel(self._preview_rect)

        # Tools
        self._converter = BatchConverter()
        self._gradient_tool = GradientTool()

        # State
        self._selected_path: Optional[str] = None
        self._status_message: str = f"Loaded {self._gallery.file_count()} files"
        self._status_timer: float = 0.0
        self._prev_mouse_pressed: bool = False

        # Font
        self._font = pygame.font.SysFont("consolas,dejavusansmono,monospace", 11)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _layout(self) -> None:
        """Compute sub-panel rectangles based on current window size."""
        w, h = self._screen.get_size()
        status_h = 24

        gallery_w = int(w * GALLERY_RATIO)
        right_w = w - gallery_w
        content_h = h - status_h

        # Right side: top half = panel, bottom half = preview
        panel_h = content_h // 2
        preview_h = content_h - panel_h

        self._gallery_rect = pygame.Rect(0, 0, gallery_w, content_h)
        self._panel_rect = pygame.Rect(gallery_w, 0, right_w, panel_h)
        self._preview_rect = pygame.Rect(gallery_w, panel_h, right_w, preview_h)
        self._status_rect = pygame.Rect(0, content_h, w, status_h)

    def _resize(self) -> None:
        """Handle window resize."""
        self._layout()
        self._gallery.set_rect(self._gallery_rect)
        self._panel.set_rect(self._panel_rect)
        self._preview.set_rect(self._preview_rect)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the editor main loop at 60 fps."""
        self._running = True

        while self._running:
            dt = self._clock.tick(60) / 1000.0  # seconds

            self.handle_events()

            # Update animations
            self._gallery.update(dt)
            self._preview.update(dt)

            # Decay status message
            if self._status_timer > 0:
                self._status_timer -= dt
                if self._status_timer <= 0:
                    self._status_message = ""

            # Render
            self._screen.fill(COL_BG)
            self._gallery.render(self._screen)
            self._panel.render(self._screen)
            self._preview.render(self._screen)

            self._render_status_bar()

            pygame.display.flip()

        pygame.quit()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self) -> None:
        """Process all pending pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return

            elif event.type == pygame.VIDEORESIZE:
                self._screen = pygame.display.set_mode(
                    (event.w, event.h), pygame.RESIZABLE
                )
                self._resize()

            elif event.type == pygame.WINDOWSIZECHANGED:
                # SDL2/Pygame 2.x fires this on Wayland/WSLg resize
                self._screen = pygame.display.set_mode(
                    self._screen.get_size(), pygame.RESIZABLE
                )
                self._resize()

            elif event.type == pygame.KEYDOWN:
                self._handle_key(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self._handle_click(event.pos)
                elif event.button in (4, 5):
                    # Scroll wheel
                    direction = 1 if event.button == 5 else -1
                    if self._gallery_rect.collidepoint(event.pos):
                        self._gallery.handle_scroll(direction)

            elif event.type == pygame.MOUSEWHEEL:
                # Modern pygame scroll event
                mouse_pos = pygame.mouse.get_pos()
                if self._gallery_rect.collidepoint(mouse_pos):
                    self._gallery.handle_scroll(-event.y)

            elif event.type == pygame.MOUSEMOTION:
                self._gallery.handle_motion(event.pos)

            # Forward to sub-panels for sliders / drag
            if event.type in (
                pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP
            ):
                panel_action = self._panel.handle_event(event)
                if panel_action:
                    self._dispatch_action(panel_action)
                self._preview.handle_event(event)

        # Track button state for future use (polling fallback removed --
        # MOUSEBUTTONDOWN events work correctly in WSLg).
        buttons = pygame.mouse.get_pressed()
        self._prev_mouse_pressed = buttons[0]

    def _handle_key(self, event: pygame.event.Event) -> None:
        """Handle keyboard shortcuts."""
        key = event.key

        if key == pygame.K_ESCAPE:
            self._deactivate_tools()
            self._gallery.deselect_all()
            self._selected_path = None
            self._preview.clear()
            self._panel.clear_file_info()

        elif key == pygame.K_SPACE:
            if self._preview.has_animation:
                self._preview.set_playing(not self._preview.is_playing)

        elif key == pygame.K_c:
            action = self._panel.activate_by_shortcut("crop")
            if action:
                self._dispatch_action(action)

        elif key == pygame.K_b:
            action = self._panel.activate_by_shortcut("fill")
            if action:
                self._dispatch_action(action)

        elif key == pygame.K_g:
            action = self._panel.activate_by_shortcut("gradient_toggle")
            if action:
                self._dispatch_action(action)

        elif key == pygame.K_s:
            action = self._panel.activate_by_shortcut("save")
            if action:
                self._dispatch_action(action)

        elif key == pygame.K_DELETE:
            self._handle_delete()

    def _handle_click(self, pos: tuple[int, int]) -> None:
        """Handle a left-click."""
        # Gallery click
        if self._gallery_rect.collidepoint(pos):
            path = self._gallery.handle_click(pos)
            if path and path != self._selected_path:
                self._select_file(path)
            elif path is None:
                self._selected_path = None
                self._preview.clear()
                self._panel.clear_file_info()

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    def _select_file(self, path: str) -> None:
        """Select a file for editing and update all panels."""
        self._selected_path = path
        self._deactivate_tools()

        # Load preview
        self._preview.load_animation(path)

        # Update info panel
        info = self._converter.get_file_info(path)
        if info:
            self._panel.set_file_info(
                path=path,
                dimensions=(info["width"], info["height"]),
                frame_count=info["frame_count"],
                file_size=info["file_size"],
                fmt=info["format"],
            )
        else:
            self._panel.clear_file_info()

        self._set_status(f"Selected: {Path(path).name}")

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _dispatch_action(self, action: dict) -> None:
        """Dispatch an action dict from the editor panel."""
        act = action.get("action", "")
        params = action.get("params", {})

        if act == "crop":
            self._preview.set_crop_mode(True)
            self._set_status("Crop: drag a rectangle on the preview, then press S to save")

        elif act == "fill":
            self._preview.set_fill_mode(True)
            self._set_status("Fill: drag a rectangle to black-fill, then press S to save")

        elif act == "gradient_toggle":
            opacity = params.get("opacity", int(self._panel.get_slider_value("gradient_opacity")))
            size = params.get("size", int(self._panel.get_slider_value("gradient_size")))
            self._preview.toggle_gradient(opacity, size)
            state = "ON" if self._preview.gradient_enabled else "OFF"
            self._set_status(f"Gradient preview: {state}")

        elif act == "save":
            self._handle_save(params)

        elif act == "convert":
            self._handle_convert()

        elif act == "padding":
            self._handle_padding(params.get("size", 0))

        elif act == "speed":
            self._handle_speed(params.get("multiplier", 1.0))

        elif act == "slider_change":
            slider_name = action.get("slider", "")
            value = action.get("value", 0)
            if slider_name in ("gradient_opacity", "gradient_size"):
                if self._preview.gradient_enabled:
                    self._preview.set_gradient_params(
                        opacity=int(self._panel.get_slider_value("gradient_opacity")),
                        size=int(self._panel.get_slider_value("gradient_size")),
                    )

    # ------------------------------------------------------------------
    # Tool operations
    # ------------------------------------------------------------------

    def _handle_save(self, params: dict) -> None:
        """Save the current file with any active tool modifications."""
        if not self._selected_path:
            self._set_status("No file selected")
            return

        path = self._selected_path
        out_path = path  # overwrite in place

        # Apply crop if active
        crop_rect = self._preview.get_crop_rect()
        if crop_rect:
            ok = self._converter.apply_crop(path, crop_rect, out_path)
            if ok:
                self._set_status(f"Cropped and saved: {Path(out_path).name}")
                self._preview.set_crop_mode(False)
                self._panel.deactivate_tools()
                self._select_file(out_path)  # reload
                return
            else:
                self._set_status("Crop failed -- check logs")
                return

        # Apply fill if active
        fill_rect = self._preview.get_fill_rect()
        if fill_rect:
            ok = self._converter.apply_fill(
                path, fill_rect, (0, 0, 0, 255), out_path
            )
            if ok:
                self._set_status(f"Fill applied and saved: {Path(out_path).name}")
                self._preview.set_fill_mode(False)
                self._panel.deactivate_tools()
                self._select_file(out_path)
                return
            else:
                self._set_status("Fill failed -- check logs")
                return

        # Apply gradient bake if enabled
        if self._preview.gradient_enabled:
            opacity = int(self._panel.get_slider_value("gradient_opacity"))
            g_size = int(self._panel.get_slider_value("gradient_size"))
            ok = self._gradient_tool.bake_gradient(path, out_path, opacity, g_size)
            if ok:
                self._set_status(f"Gradient baked and saved: {Path(out_path).name}")
                self._preview.toggle_gradient(opacity, g_size)  # turn off preview
                self._panel.deactivate_tools()
                self._select_file(out_path)
                return
            else:
                self._set_status("Gradient bake failed -- check logs")
                return

        # Speed adjustment if not 1.0
        speed = params.get("speed", 1.0)
        if speed != 1.0:
            ok = self._converter.adjust_speed(path, speed, out_path)
            if ok:
                self._set_status(f"Speed {speed:.2f}x saved: {Path(out_path).name}")
                self._select_file(out_path)
                return
            else:
                self._set_status("Speed adjustment failed")
                return

        # Padding if > 0
        padding = params.get("padding", 0)
        if padding > 0:
            ok = self._converter.apply_padding(
                path, padding, (0, 0, 0, 255), out_path
            )
            if ok:
                self._set_status(f"Padding {padding}px saved: {Path(out_path).name}")
                self._select_file(out_path)
                return
            else:
                self._set_status("Padding failed")
                return

        self._set_status("Nothing to save (no tool active or changes pending)")

    def _handle_convert(self) -> None:
        """Convert the selected file to WebP."""
        if not self._selected_path:
            self._set_status("No file selected")
            return

        path = self._selected_path
        if path.lower().endswith(".webp"):
            self._set_status("File is already WebP")
            return

        out_path = str(Path(path).with_suffix(".webp"))
        speed = self._panel.get_slider_value("speed")
        ok = self._converter.convert_file(path, out_path, speed_multiplier=speed)
        if ok:
            self._set_status(f"Converted to WebP: {Path(out_path).name}")
            # Reload gallery to pick up new file
            self._gallery.load_directory(self._directory)
            self._select_file(out_path)
        else:
            self._set_status("Conversion failed -- check logs")

    def _handle_padding(self, size: int) -> None:
        """Apply padding immediately."""
        if not self._selected_path:
            self._set_status("No file selected")
            return
        if size <= 0:
            self._set_status("Padding size is 0 -- adjust the slider first")
            return

        path = self._selected_path
        ok = self._converter.apply_padding(path, size, (0, 0, 0, 255), path)
        if ok:
            self._set_status(f"Added {size}px padding: {Path(path).name}")
            self._select_file(path)
        else:
            self._set_status("Padding failed -- check logs")

    def _handle_speed(self, multiplier: float) -> None:
        """Apply speed change immediately."""
        if not self._selected_path:
            self._set_status("No file selected")
            return
        if multiplier == 1.0:
            self._set_status("Speed is 1.0x -- nothing to change")
            return

        path = self._selected_path
        ok = self._converter.adjust_speed(path, multiplier, path)
        if ok:
            self._set_status(f"Speed {multiplier:.2f}x applied: {Path(path).name}")
            self._select_file(path)
        else:
            self._set_status("Speed adjustment failed -- check logs")

    def _handle_delete(self) -> None:
        """Delete the selected file from disk and gallery."""
        if not self._selected_path:
            self._set_status("No file selected")
            return

        path = self._selected_path
        name = Path(path).name

        try:
            os.remove(path)
            self._gallery.remove_file(path)
            self._selected_path = None
            self._preview.clear()
            self._panel.clear_file_info()
            self._set_status(f"Deleted: {name}")
        except OSError:
            logger.exception("Failed to delete %s", path)
            self._set_status(f"Delete failed: {name}")

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        """Display a status message for 5 seconds."""
        self._status_message = message
        self._status_timer = 5.0
        logger.info("Status: %s", message)

    def _render_status_bar(self) -> None:
        """Draw the bottom status bar."""
        pygame.draw.rect(self._screen, COL_STATUS_BG, self._status_rect)

        # Left: status message
        if self._status_message:
            msg_surf = self._font.render(self._status_message, True, COL_TEXT)
            self._screen.blit(msg_surf, (self._status_rect.x + 8, self._status_rect.y + 5))

        # Right: file count
        count_text = f"{self._gallery.file_count()} files"
        count_surf = self._font.render(count_text, True, COL_TEXT_DIM)
        cx = self._status_rect.x + self._status_rect.width - count_surf.get_width() - 8
        self._screen.blit(count_surf, (cx, self._status_rect.y + 5))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _deactivate_tools(self) -> None:
        """Turn off all interactive tools on the preview and panel."""
        self._preview.set_crop_mode(False)
        self._preview.set_fill_mode(False)
        if self._preview.gradient_enabled:
            # Keep gradient on/off as-is, but deactivate the panel button
            pass
        self._panel.deactivate_tools()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for ``python -m editor.main``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    directory = "animations"
    if len(sys.argv) > 1:
        directory = sys.argv[1]

    app = EditorApp(directory=directory)
    app.run()


if __name__ == "__main__":
    main()
