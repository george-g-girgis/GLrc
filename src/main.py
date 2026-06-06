"""
GLrc — Transparent lyrics overlay for Windows 11.

Features:
  - Borderless, always-on-top, click-through overlay
  - Edit Mode (draggable/resizable) ↔ Lock Mode (click-through)
  - Multi-line karaoke mode (prev / current / next)
  - System tray icon with context menu
  - Color theming (fill + outline)
  - State persistence across restarts
  - Native Win32 global hotkeys (no admin required)
"""

import sys
import os
import time
import logging
import ctypes
import ctypes.wintypes

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QSystemTrayIcon, QMenu, QColorDialog,
)
from PyQt6.QtGui import (
    QPainter, QPainterPath, QPen, QColor, QFont,
    QBrush, QCursor, QIcon, QAction, QFontMetrics,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtProperty, QPropertyAnimation,
    QParallelAnimationGroup, QEasingCurve, QRect,
    QAbstractNativeEventFilter, QSize,
)

from lyrics_engine import LyricsEngine
from config import load_config, save_config
from settings_ui import SettingsDialog

# ── Logging ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("GLrc")

# ── Constants ────────────────────────────────────────────────────────────

GRIP_SIZE = 8

# Win32 constants for RegisterHotKey
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

HOTKEY_ID_LOCK = 1
HOTKEY_ID_UNLOCK = 2
HOTKEY_ID_OFFSET_MINUS = 3
HOTKEY_ID_OFFSET_PLUS = 4

# Resolve icon path relative to script / frozen exe
if getattr(sys, "frozen", False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(_BASE_DIR, "assets", "myicon.ico")


# ── Global Hotkey Filter ─────────────────────────────────────────────────

class HotkeyFilter(QAbstractNativeEventFilter):
    """Application-level native event filter for global hotkeys.
    
    Uses QAbstractNativeEventFilter instead of overriding QWidget.nativeEvent
    because the latter crashes on Python 3.14 + PyQt6 6.11 due to SIP binding
    issues with the return type.
    """

    def __init__(self):
        super().__init__()
        self.overlay = None  # Set after overlay is created

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG":
                # Read message ID from the MSG struct at offset 8 (after HWND)
                addr = int(message)
                msg_id = ctypes.c_uint32.from_address(addr + 8).value
                if msg_id == WM_HOTKEY and self.overlay:
                    wparam = ctypes.c_uint64.from_address(addr + 16).value
                    if wparam == HOTKEY_ID_LOCK:
                        self.overlay.set_lock_mode()
                        return True, 0
                    elif wparam == HOTKEY_ID_UNLOCK:
                        self.overlay.set_edit_mode()
                        return True, 0
                    elif wparam == HOTKEY_ID_OFFSET_MINUS:
                        self.overlay.adjust_sync_offset(-500)
                        return True, 0
                    elif wparam == HOTKEY_ID_OFFSET_PLUS:
                        self.overlay.adjust_sync_offset(500)
                        return True, 0
        except Exception:
            log.debug("HotkeyFilter error", exc_info=True)
        return False, 0


# ── OutlinedLabel ────────────────────────────────────────────────────────

class OutlinedLabel(QLabel):
    """A label that renders text with a colored fill and outline using QPainterPath."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.font_family = "Segoe UI Semibold"
        self.font_size = 32
        self._opacity = 1.0
        self._y_shift = 0.0
        self._fill_color = QColor("white")
        self._outline_color = QColor("black")
        
        # Add generous padding so animations and outlines don't clip
        self.setContentsMargins(40, 40, 40, 40)
        
        self.update_font()

    def update_font(self):
        my_font = QFont(self.font_family, self.font_size)
        my_font.setWeight(QFont.Weight.DemiBold)
        self.setFont(my_font)
        self.updateGeometry()
        self.update()

    def set_font_size(self, size: int):
        self.font_size = max(10, size)
        self.update_font()

    def set_colors(self, fill: QColor, outline: QColor):
        self._fill_color = fill
        self._outline_color = outline
        self.update()

    # ── Animatable properties ──

    @pyqtProperty(float)
    def opacity(self):
        return self._opacity

    @opacity.setter
    def opacity(self, val):
        self._opacity = val
        self.update()

    @pyqtProperty(float)
    def y_shift(self):
        return self._y_shift

    @y_shift.setter
    def y_shift(self, val):
        self._y_shift = val
        self.update()

    def minimumSizeHint(self):
        metrics = QFontMetrics(self.font())
        return QSize(50, metrics.height() + 80)

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        w = metrics.horizontalAdvance(self.text()) + 80
        h = metrics.height() + 80
        return QSize(w, h)

    # ── Paint ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        path = QPainterPath()
        font = self.font()
        text = self.text()

        metrics = painter.fontMetrics()
        
        # Center manually
        x = float((self.rect().width() - metrics.horizontalAdvance(text)) / 2)
        y = float((self.rect().height() - metrics.height()) / 2 + metrics.ascent()) + self._y_shift

        path.addText(x, y, font, text)

        # Draw outline
        thickness = max(2, self.font_size // 10)
        pen = QPen(self._outline_color)
        pen.setWidth(thickness)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Draw fill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._fill_color))
        painter.drawPath(path)


# ── Main Overlay ─────────────────────────────────────────────────────────

class GLrcOverlay(QWidget):
    def __init__(self):
        super().__init__()

        # ── Load config ──
        self.cfg = load_config()

        self.engine = LyricsEngine()
        self.engine.target_app_id = self.cfg.get("target_app_id", None)
        
        self.locked = False
        self.hovered = False
        self.is_playing = False
        self.last_text = ""
        self.display_mode = self.cfg.get("display_mode", "single")

        # Drag state
        self.old_pos = None

        # Resize state
        self._resizing = False
        self._resize_edge = None
        self._resize_origin = None
        self._resize_geo = None

        # Animation group (prevent GC)
        self._anim_group = None

        # Bug fix: track-change flag to prevent interpolation glitch
        self._track_just_changed = False
        self._last_os_ms = 0
        self._current_ms = 0
        self._last_read_time = time.time()

        # Current track info for tray tooltip
        self._current_track_info = ""
        self.settings_dialog = None

        self.init_ui()
        self.init_tray()
        self.setup_timers()
        self.poll_track()  # Initial poll

        # Restore lock state from config
        if self.cfg.get("locked", False):
            self.set_lock_mode()

    # ── UI setup ─────────────────────────────────────────────────────

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 60)
        self.setStyleSheet("background: transparent; border: none;")

        # ── Geometry: restore or default ──
        screen_geo = QApplication.primaryScreen().geometry()
        w = self.cfg.get("width") or screen_geo.width()
        h = self.cfg.get("height") or 150
        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            x = 0
            y = screen_geo.height() - 250
        self.setGeometry(x, y, w, h)

        # ── Colors from config ──
        fill = QColor(self.cfg.get("fill_color", "#FFFFFF"))
        outline = QColor(self.cfg.get("outline_color", "#000000"))
        font_size = self.cfg.get("font_size", 32)

        # ── Layout ──
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(GRIP_SIZE, GRIP_SIZE, GRIP_SIZE, GRIP_SIZE)
        self.main_layout.setSpacing(0)

        # ── Labels ──
        # Multi-line mode: prev (dimmed), current, next (dimmed)
        self.label_prev = OutlinedLabel("")
        self.label_current = OutlinedLabel("GLrc (Edit Mode)")
        self.label_next = OutlinedLabel("")

        for lbl in (self.label_prev, self.label_current, self.label_next):
            lbl.setStyleSheet("background: transparent; border: none;")
            lbl.setMouseTracking(True)
            lbl.set_font_size(font_size)
            lbl.set_colors(fill, outline)

        # Dimmed labels for surrounding lines
        self.label_prev.set_font_size(max(10, int(font_size * 0.65)))
        self.label_next.set_font_size(max(10, int(font_size * 0.65)))
        self.label_prev._opacity = 0.4
        self.label_next._opacity = 0.4

        self.main_layout.addWidget(
            self.label_prev, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.main_layout.addWidget(
            self.label_current, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.main_layout.addWidget(
            self.label_next, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # Set visibility based on display mode
        self._apply_display_mode()

    def _apply_display_mode(self):
        """Show/hide surrounding labels based on display_mode."""
        multi = self.display_mode == "multi"
        self.label_prev.setVisible(multi)
        self.label_next.setVisible(multi)
        self._update_minimum_height()

    def _update_minimum_height(self):
        """Dynamically set the minimum window height so the labels don't get squished and clip."""
        # Use layout's minimumSizeHint() to prevent vertical squishing
        self.main_layout.invalidate()
        min_h = self.main_layout.minimumSize().height()
        self.setMinimumHeight(min_h)
        # We don't adjustSize horizontally so the window width is preserved

    # ── DWM border removal ───────────────────────────────────────────

    def _remove_dwm_border(self):
        """Strip the border that Windows 11 DWM forces on frameless windows."""
        hwnd = int(self.winId())
        dwmapi = ctypes.windll.dwmapi

        DWMWA_BORDER_COLOR = 34
        DWMWA_COLOR_NONE = 0xFFFFFFFE
        color = ctypes.c_uint32(DWMWA_COLOR_NONE)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_BORDER_COLOR,
            ctypes.byref(color), ctypes.sizeof(color),
        )

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        pref = ctypes.c_int(DWMWCP_DONOTROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref),
        )

    # ── Native global hotkeys (RegisterHotKey) ───────────────────────

    def _register_hotkeys(self):
        """Register Ctrl+Shift+L and Ctrl+Shift+U as global hotkeys.
        
        Uses HWND=0 (thread message queue) because we intercept WM_HOTKEY
        via the app-level QAbstractNativeEventFilter, not per-window.
        This also means registrations survive window recreation from
        setWindowFlags().
        """
        self._unregister_hotkeys()  # Clean up any previous registration
        mods = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
        user32 = ctypes.windll.user32

        if not user32.RegisterHotKey(0, HOTKEY_ID_LOCK, mods, 0x4C):  # 'L'
            log.warning("Failed to register Ctrl+Shift+L hotkey.")
        else:
            log.info("Registered Ctrl+Shift+L (Lock).")
        if not user32.RegisterHotKey(0, HOTKEY_ID_UNLOCK, mods, 0x55):  # 'U'
            log.warning("Failed to register Ctrl+Shift+U hotkey.")
        else:
            log.info("Registered Ctrl+Shift+U (Unlock).")
        
        # Win32 VK codes: VK_LEFT = 0x25, VK_RIGHT = 0x27
        if not user32.RegisterHotKey(0, HOTKEY_ID_OFFSET_MINUS, mods, 0x25):
            log.warning("Failed to register Ctrl+Shift+Left hotkey.")
        if not user32.RegisterHotKey(0, HOTKEY_ID_OFFSET_PLUS, mods, 0x27):
            log.warning("Failed to register Ctrl+Shift+Right hotkey.")

    def _unregister_hotkeys(self):
        """Clean up hotkeys on exit."""
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(0, HOTKEY_ID_LOCK)
        user32.UnregisterHotKey(0, HOTKEY_ID_UNLOCK)
        user32.UnregisterHotKey(0, HOTKEY_ID_OFFSET_MINUS)
        user32.UnregisterHotKey(0, HOTKEY_ID_OFFSET_PLUS)


    # ── Lock / Unlock & Offset ───────────────────────────────────────

    def set_lock_mode(self):
        if not self.locked:
            self.locked = True
            flags = self.windowFlags() | Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.show()
            self._remove_dwm_border()
            self.show_temp_message("Mode: LOCKED 🔒")
            self._update_tray_menu()
            self._save_state()

    def set_edit_mode(self):
        if self.locked:
            self.locked = False
            flags = self.windowFlags() & ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.show()
            self._remove_dwm_border()
            self.show_temp_message("Mode: EDIT 🖱️")
            self._update_tray_menu()
            self._save_state()

    def show_temp_message(self, msg: str):
        self.label_current.setText(msg)
        self.label_current.update()
        self.last_text = msg

    def adjust_sync_offset(self, delta_ms: int):
        self.engine.sync_offset_ms += delta_ms
        sign = "+" if self.engine.sync_offset_ms > 0 else ""
        text_val = f"{sign}{self.engine.sync_offset_ms} ms"
        self.show_temp_message(f"Sync Offset: {text_val}")
        
        if getattr(self, "settings_dialog", None) and self.settings_dialog.isVisible():
            self.settings_dialog.sync_slider.blockSignals(True)
            self.settings_dialog.sync_slider.setValue(self.engine.sync_offset_ms)
            self.settings_dialog.sync_label.setText(text_val)
            self.settings_dialog.sync_slider.blockSignals(False)

    # ── Keyboard (local: font size when focused & unlocked) ──────────

    def keyPressEvent(self, event):
        if self.locked:
            return
        mods = event.modifiers()
        if mods == (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
        ):
            if event.key() == Qt.Key.Key_Up:
                new_size = self.label_current.font_size + 4
                self._set_all_font_sizes(new_size)
                self._save_state()
            elif event.key() == Qt.Key.Key_Down:
                new_size = self.label_current.font_size - 4
                self._set_all_font_sizes(new_size)
                self._save_state()

    def _set_all_font_sizes(self, size: int):
        self.label_prev.set_font_size(max(10, int(size * 0.65)))
        self.label_current.set_font_size(size)
        self.label_next.set_font_size(max(10, int(size * 0.65)))
        self._update_minimum_height()
        
        if getattr(self, "settings_dialog", None) and self.settings_dialog.isVisible():
            self.settings_dialog.font_slider.blockSignals(True)
            self.settings_dialog.font_slider.setValue(size)
            self.settings_dialog.font_label.setText(str(size))
            self.settings_dialog.font_slider.blockSignals(False)

    # ── Timers ───────────────────────────────────────────────────────

    def setup_timers(self):
        # Poll track changes every 3s
        self.track_timer = QTimer(self)
        self.track_timer.timeout.connect(self.poll_track)
        self.track_timer.start(3000)

        # UI update every 100ms
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start(100)

    def poll_track(self):
        """Check for track changes and fetch new lyrics."""
        prev_id = self.engine.current_track_id
        result = self.engine.update()

        if result and result["id"] != prev_id:
            # Track changed — set flag to snap position on next UI tick
            self._track_just_changed = True
            self._current_track_info = f"{result['name']} — {result['artist']}"
            if hasattr(self, "tray_icon"):
                self.tray_icon.setToolTip(f"GLrc: {self._current_track_info}")
            if getattr(self, "settings_dialog", None):
                self.settings_dialog.update_track_info(result['name'], result['artist'])

    # ── UI update (every 100ms) ──────────────────────────────────────

    def update_ui(self):
        is_playing = self.engine.get_is_playing()
        if not is_playing:
            self._update_labels("", "Music is paused", "")
            return

        os_ms = self.engine.get_position_ms()
        now = time.time()

        # Bug fix: on track change, snap to fresh OS position
        if self._track_just_changed:
            self._current_ms = os_ms
            self._last_os_ms = os_ms
            self._last_read_time = now
            self._track_just_changed = False
        elif os_ms != self._last_os_ms:
            # OS gave fresh position — snap
            self._current_ms = os_ms
            self._last_os_ms = os_ms
            self._last_read_time = now
        else:
            # Stale — interpolate forward
            elapsed = (now - self._last_read_time) * 1000
            self._current_ms = self._last_os_ms + int(elapsed)

        if self.display_mode == "multi":
            prev, cur, nxt = self.engine.get_surrounding_lyrics(self._current_ms)
            self._update_labels(prev, cur, nxt)
        else:
            current_lyric = self.engine.get_current_lyric(self._current_ms)
            self._update_labels("", current_lyric, "")

    def _update_labels(self, prev: str, current: str, nxt: str):
        """Update all labels and trigger animation only if current line changed."""
        if current != self.last_text:
            self.label_current.setText(current)
            self.last_text = current
            self._animate_fade_up()

        if self.display_mode == "multi":
            if self.label_prev.text() != prev or self.label_next.text() != nxt:
                self.label_prev.setText(prev)
                self.label_next.setText(nxt)

    # ── Animation ────────────────────────────────────────────────────

    def _animate_fade_up(self):
        """Fade-up transition on the labels."""
        if (
            self._anim_group
            and self._anim_group.state() == QPropertyAnimation.State.Running
        ):
            self._anim_group.stop()

        self._anim_group = QParallelAnimationGroup()

        labels = [self.label_current]
        if self.display_mode == "multi":
            labels.extend([self.label_prev, self.label_next])

        for label in labels:
            target_opacity = 1.0 if label == self.label_current else 0.4
            
            fade = QPropertyAnimation(label, b"opacity")
            fade.setDuration(300)
            fade.setStartValue(0.0)
            fade.setEndValue(target_opacity)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim_group.addAnimation(fade)

            if self.display_mode == "single":
                rise = QPropertyAnimation(label, b"y_shift")
                rise.setDuration(300)
                rise.setStartValue(15.0)
                rise.setEndValue(0.0)
                rise.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._anim_group.addAnimation(rise)
            else:
                label.y_shift = 0.0

        self._anim_group.start()

    # ── System Tray ──────────────────────────────────────────────────

    def init_tray(self):
        """Set up the system tray icon and its context menu."""
        self.tray_icon = QSystemTrayIcon(self)

        if os.path.exists(ICON_PATH):
            self.tray_icon.setIcon(QIcon(ICON_PATH))
        else:
            # Fallback to app icon
            self.tray_icon.setIcon(
                self.style().standardIcon(
                    self.style().StandardPixmap.SP_MediaPlay
                )
            )

        self.tray_icon.setToolTip("GLrc")
        self.tray_icon.activated.connect(self._on_tray_activated)

        self.tray_menu = QMenu()
        self._build_tray_menu()
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def open_settings(self):
        if getattr(self, "settings_dialog", None):
            self.settings_dialog.close()
            self.settings_dialog.deleteLater()
            
        self.settings_dialog = SettingsDialog(self)
        
        # Pre-fill current track info if available
        if self.engine.current_track_id:
            try:
                name, artist = self._current_track_info.split(" — ")
                self.settings_dialog.update_track_info(name, artist)
            except ValueError:
                pass
                
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _build_tray_menu(self):
        """Populate the tray context menu."""
        self.tray_menu.clear()

        # Settings
        act_settings = QAction("⚙️ Open Settings", self)
        act_settings.triggered.connect(self.open_settings)
        self.tray_menu.addAction(act_settings)
        
        self.tray_menu.addSeparator()

        # Lock / Unlock
        if self.locked:
            action_toggle = QAction("🖱️ Switch to Edit Mode", self)
            action_toggle.triggered.connect(self.set_edit_mode)
        else:
            action_toggle = QAction("🔒 Switch to Lock Mode", self)
            action_toggle.triggered.connect(self.set_lock_mode)
        self.tray_menu.addAction(action_toggle)

        self.tray_menu.addSeparator()

        # Display mode
        mode_menu = self.tray_menu.addMenu("📝 Display Mode")
        act_single = QAction("Single Line", self)
        act_single.setCheckable(True)
        act_single.setChecked(self.display_mode == "single")
        act_single.triggered.connect(lambda: self._set_display_mode("single"))

        act_multi = QAction("Multi-Line (Karaoke)", self)
        act_multi.setCheckable(True)
        act_multi.setChecked(self.display_mode == "multi")
        act_multi.triggered.connect(lambda: self._set_display_mode("multi"))

        mode_menu.addAction(act_single)
        mode_menu.addAction(act_multi)

        self.tray_menu.addSeparator()

        # Font size
        font_menu = self.tray_menu.addMenu("🔤 Font Size")
        act_increase = QAction("Increase  (Ctrl+Shift+↑)", self)
        act_increase.triggered.connect(
            lambda: (
                self._set_all_font_sizes(self.label_current.font_size + 4),
                self._save_state(),
            )
        )
        act_decrease = QAction("Decrease  (Ctrl+Shift+↓)", self)
        act_decrease.triggered.connect(
            lambda: (
                self._set_all_font_sizes(self.label_current.font_size - 4),
                self._save_state(),
            )
        )
        font_menu.addAction(act_increase)
        font_menu.addAction(act_decrease)

        self.tray_menu.addSeparator()

        # Colors
        act_fill = QAction("🎨 Text Color...", self)
        act_fill.triggered.connect(self._pick_fill_color)
        self.tray_menu.addAction(act_fill)

        act_outline = QAction("🖊️ Outline Color...", self)
        act_outline.triggered.connect(self._pick_outline_color)
        self.tray_menu.addAction(act_outline)

        self.tray_menu.addSeparator()

        # Quit
        act_quit = QAction("❌ Quit", self)
        act_quit.triggered.connect(self._quit)
        self.tray_menu.addAction(act_quit)

    def _update_tray_menu(self):
        self._build_tray_menu()

    def _on_tray_activated(self, reason):
        """Left-click opens settings."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    # ── Display mode ─────────────────────────────────────────────────

    def _set_display_mode(self, mode: str):
        self.display_mode = mode
        self._apply_display_mode()
        self._update_tray_menu()
        self._save_state()
        self.last_text = ""  # Force refresh

    # ── Color pickers ────────────────────────────────────────────────

    def set_colors(self, fill: QColor, outline: QColor):
        for lbl in (self.label_prev, self.label_current, self.label_next):
            lbl.set_colors(fill, outline)
        self.cfg["fill_color"] = fill.name()
        self.cfg["outline_color"] = outline.name()

    def _pick_fill_color(self):
        color = QColorDialog.getColor(
            self.label_current._fill_color, self, "Pick Text Color"
        )
        if color.isValid():
            self.set_colors(color, self.label_current._outline_color)
            self._save_state()

    def _pick_outline_color(self):
        color = QColorDialog.getColor(
            self.label_current._outline_color, self, "Pick Outline Color"
        )
        if color.isValid():
            self.set_colors(self.label_current._fill_color, color)
            self._save_state()

    # ── State persistence ────────────────────────────────────────────

    def _save_state(self):
        """Persist current state to config.json."""
        geo = self.geometry()
        self.cfg.update({
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
            "font_size": self.label_current.font_size,
            "locked": self.locked,
            "display_mode": self.display_mode,
            "fill_color": self.label_current._fill_color.name(),
            "outline_color": self.label_current._outline_color.name(),
        })
        save_config(self.cfg)

    # ── Mouse hover ──────────────────────────────────────────────────

    def enterEvent(self, event):
        self.hovered = True

    def leaveEvent(self, event):
        self.hovered = False

    # ── Edge detection for resize ────────────────────────────────────

    def _edge_at(self, pos):
        r = self.rect()
        x, y = pos.x(), pos.y()
        g = GRIP_SIZE

        on_left = x < g
        on_right = x > r.width() - g
        on_top = y < g
        on_bottom = y > r.height() - g

        if on_top and on_left:
            return "top-left"
        if on_top and on_right:
            return "top-right"
        if on_bottom and on_left:
            return "bottom-left"
        if on_bottom and on_right:
            return "bottom-right"
        if on_left:
            return "left"
        if on_right:
            return "right"
        if on_top:
            return "top"
        if on_bottom:
            return "bottom"
        return None

    _CURSOR_MAP = {
        "top": Qt.CursorShape.SizeVerCursor,
        "bottom": Qt.CursorShape.SizeVerCursor,
        "left": Qt.CursorShape.SizeHorCursor,
        "right": Qt.CursorShape.SizeHorCursor,
        "top-left": Qt.CursorShape.SizeFDiagCursor,
        "bottom-right": Qt.CursorShape.SizeFDiagCursor,
        "top-right": Qt.CursorShape.SizeBDiagCursor,
        "bottom-left": Qt.CursorShape.SizeBDiagCursor,
    }

    # ── Mouse handling ───────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        if self.locked:
            return

        pos = event.position().toPoint()

        if self._resizing:
            self._do_resize(event.globalPosition().toPoint())
            return

        if self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()
            return

        edge = self._edge_at(pos)
        if edge:
            self.setCursor(QCursor(self._CURSOR_MAP[edge]))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, event):
        if self.locked or event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position().toPoint()
        edge = self._edge_at(pos)

        if edge:
            self._resizing = True
            self._resize_edge = edge
            self._resize_origin = event.globalPosition().toPoint()
            self._resize_geo = self.geometry()
        else:
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing or self.old_pos is not None:
                self._save_state()  # Persist position after drag/resize
            self._resizing = False
            self._resize_edge = None
            self.old_pos = None

    def _do_resize(self, global_pos):
        dx = global_pos.x() - self._resize_origin.x()
        dy = global_pos.y() - self._resize_origin.y()
        geo = QRect(self._resize_geo)
        edge = self._resize_edge
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        if "right" in edge:
            geo.setRight(self._resize_geo.right() + dx)
        if "left" in edge:
            new_left = self._resize_geo.left() + dx
            if geo.right() - new_left >= min_w:
                geo.setLeft(new_left)
        if "bottom" in edge:
            geo.setBottom(self._resize_geo.bottom() + dy)
        if "top" in edge:
            new_top = self._resize_geo.top() + dy
            if geo.bottom() - new_top >= min_h:
                geo.setTop(new_top)

        if geo.width() >= min_w and geo.height() >= min_h:
            self.setGeometry(geo)

    # ── Lifecycle ────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)

    def closeEvent(self, event):
        """Save state and clean up on exit."""
        self._save_state()
        self._unregister_hotkeys()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        super().closeEvent(event)

    def _quit(self):
        """Clean shutdown from tray menu."""
        self._save_state()
        self._unregister_hotkeys()
        self.tray_icon.hide()
        QApplication.quit()


# ── Entry point ──────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GLrc")
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray

    # Install global hotkey filter before creating the overlay
    hotkey_filter = HotkeyFilter()
    app.installNativeEventFilter(hotkey_filter)

    overlay = GLrcOverlay()
    hotkey_filter.overlay = overlay  # Wire up the callback target

    overlay.show()
    overlay.open_settings()
    overlay._remove_dwm_border()
    overlay._register_hotkeys()  # Register once after window is shown

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
