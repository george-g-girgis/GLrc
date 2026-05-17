import sys
import time
import ctypes
import ctypes.wintypes
import keyboard

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QColor, QFont, QBrush, QCursor
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, pyqtProperty, QObject,
    QRect, QPoint, QPropertyAnimation, QParallelAnimationGroup,
    QEasingCurve,
)

from engine import LyricsEngine

GRIP_SIZE = 8


class HotkeySignals(QObject):
    lock_triggered = pyqtSignal()
    unlock_triggered = pyqtSignal()


class OutlinedLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_family = 'Segoe UI Semibold'
        self.font_size = 32
        self._opacity = 1.0
        self._y_shift = 0.0
        self.update_font()

    def update_font(self):
        my_font = QFont(self.font_family, self.font_size)
        my_font.setWeight(QFont.Weight.DemiBold)
        self.setFont(my_font)
        self.update()

    def set_font_size(self, size):
        self.font_size = max(10, size)
        self.update_font()

    # -- Animatable properties --
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        path = QPainterPath()
        font = self.font()
        text = self.text()

        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

        x = float(text_rect.x())
        y = float(text_rect.y() + metrics.ascent()) + self._y_shift

        path.addText(x, y, font, text)

        thickness = max(2, self.font_size // 10)
        pen = QPen(QColor('black'), thickness)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor('white')))
        painter.drawPath(path)


class SpotLrcOverlay(QWidget):
    def __init__(self):
        super().__init__()

        self.engine = LyricsEngine()
        self.locked = False
        self.hovered = False

        self.is_playing = False
        self.last_text = ""

        # Drag state
        self.old_pos = None

        # Resize state
        self._resizing = False
        self._resize_edge = None
        self._resize_origin = None
        self._resize_geo = None

        # Animation group (kept alive to avoid GC)
        self._anim_group = None

        self.init_ui()
        self.setup_hotkeys()
        self.setup_timers()
        self.poll_track()

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

        screen_geo = QApplication.primaryScreen().geometry()
        self.resize(screen_geo.width(), 150)
        self.move(0, screen_geo.height() - 250)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(GRIP_SIZE, GRIP_SIZE, GRIP_SIZE, GRIP_SIZE)

        self.lyric_label = OutlinedLabel("SpotLrc (Edit Mode)")
        self.lyric_label.setStyleSheet("background: transparent; border: none;")
        self.lyric_label.setMouseTracking(True)
        self.layout.addWidget(self.lyric_label, alignment=Qt.AlignmentFlag.AlignCenter)

    def _remove_dwm_border(self):
        """Use Win32 API to strip the border that Windows 11 DWM forces on all windows."""
        hwnd = int(self.winId())
        dwmapi = ctypes.windll.dwmapi

        DWMWA_BORDER_COLOR = 34
        DWMWA_COLOR_NONE = 0xFFFFFFFE
        color = ctypes.c_uint32(DWMWA_COLOR_NONE)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(color), ctypes.sizeof(color))

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        pref = ctypes.c_int(DWMWCP_DONOTROUND)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref))

    def setup_hotkeys(self):
        self.signals = HotkeySignals()
        self.signals.lock_triggered.connect(self.set_lock_mode)
        self.signals.unlock_triggered.connect(self.set_edit_mode)

        # Only Lock/Unlock are global hotkeys
        keyboard.add_hotkey('ctrl+shift+l', self.signals.lock_triggered.emit)
        keyboard.add_hotkey('ctrl+shift+u', self.signals.unlock_triggered.emit)

    def keyPressEvent(self, event):
        """Handle Ctrl+Shift+Up/Down for font size — only when overlay is focused & unlocked."""
        if self.locked:
            return
        mods = event.modifiers()
        if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Up:
                self.lyric_label.set_font_size(self.lyric_label.font_size + 4)
            elif event.key() == Qt.Key.Key_Down:
                self.lyric_label.set_font_size(self.lyric_label.font_size - 4)

    def set_lock_mode(self):
        if not self.locked:
            self.locked = True
            flags = self.windowFlags() | Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.show()
            self._remove_dwm_border()
            self.show_temp_message("Mode: LOCKED 🔒")

    def set_edit_mode(self):
        if self.locked:
            self.locked = False
            flags = self.windowFlags() & ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.show()
            self._remove_dwm_border()
            self.show_temp_message("Mode: EDIT 🖱️")

    def show_temp_message(self, msg):
        self.lyric_label.setText(msg)
        self.lyric_label.update()
        self.last_text = msg

    def setup_timers(self):
        # Poll for track changes every 3s
        self.track_timer = QTimer(self)
        self.track_timer.timeout.connect(self.poll_track)
        self.track_timer.start(3000)

        # Position tracking
        self._last_os_ms = 0       # Last position the OS reported
        self._current_ms = 0       # Our smoothed position
        self._last_read_time = time.time()

        # Update UI every 100ms
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start(100)

    def poll_track(self):
        """Check for track changes and fetch new lyrics."""
        self.engine.update()

    def update_ui(self):
        """Read OS position each tick. If it moved, snap to it. If stale, interpolate +100ms."""
        is_playing = self.engine.get_is_playing()
        if not is_playing:
            self.update_lyric_text("Music is paused")
            return

        os_ms = self.engine.get_position_ms()
        now = time.time()

        if os_ms != self._last_os_ms:
            # OS gave us a fresh position — snap to it
            self._current_ms = os_ms
            self._last_os_ms = os_ms
            self._last_read_time = now
        else:
            # OS returned the same value — interpolate forward
            elapsed = (now - self._last_read_time) * 1000
            self._current_ms = self._last_os_ms + int(elapsed)
        current_lyric = self.engine.get_current_lyric(self._current_ms)
        self.update_lyric_text(current_lyric)

    def update_lyric_text(self, text):
        if text != self.last_text:
            self.lyric_label.setText(text)
            self.last_text = text
            self._animate_fade_up()

    def _animate_fade_up(self):
        """Fade-up transition: text rises from below while fading in."""
        # Stop any running animation
        if self._anim_group and self._anim_group.state() == QPropertyAnimation.State.Running:
            self._anim_group.stop()

        fade = QPropertyAnimation(self.lyric_label, b"opacity")
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        rise = QPropertyAnimation(self.lyric_label, b"y_shift")
        rise.setDuration(200)
        rise.setStartValue(12.0)
        rise.setEndValue(0.0)
        rise.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_group = QParallelAnimationGroup()
        self._anim_group.addAnimation(fade)
        self._anim_group.addAnimation(rise)
        self._anim_group.start()

    # ── Mouse hover ───────────────────────────────────────────────────
    def enterEvent(self, event):
        self.hovered = True

    def leaveEvent(self, event):
        self.hovered = False

    # ── Edge detection ────────────────────────────────────────────────
    def _edge_at(self, pos):
        r = self.rect()
        x, y = pos.x(), pos.y()
        g = GRIP_SIZE

        on_left   = x < g
        on_right  = x > r.width() - g
        on_top    = y < g
        on_bottom = y > r.height() - g

        if on_top and on_left:     return 'top-left'
        if on_top and on_right:    return 'top-right'
        if on_bottom and on_left:  return 'bottom-left'
        if on_bottom and on_right: return 'bottom-right'
        if on_left:                return 'left'
        if on_right:               return 'right'
        if on_top:                 return 'top'
        if on_bottom:              return 'bottom'
        return None

    _CURSOR_MAP = {
        'top':          Qt.CursorShape.SizeVerCursor,
        'bottom':       Qt.CursorShape.SizeVerCursor,
        'left':         Qt.CursorShape.SizeHorCursor,
        'right':        Qt.CursorShape.SizeHorCursor,
        'top-left':     Qt.CursorShape.SizeFDiagCursor,
        'bottom-right': Qt.CursorShape.SizeFDiagCursor,
        'top-right':    Qt.CursorShape.SizeBDiagCursor,
        'bottom-left':  Qt.CursorShape.SizeBDiagCursor,
    }

    # ── Mouse handling ────────────────────────────────────────────────
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
            self._resizing = False
            self._resize_edge = None
            self.old_pos = None

    def _do_resize(self, global_pos):
        dx = global_pos.x() - self._resize_origin.x()
        dy = global_pos.y() - self._resize_origin.y()
        geo = QRect(self._resize_geo)
        edge = self._resize_edge
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        if 'right' in edge:
            geo.setRight(self._resize_geo.right() + dx)
        if 'left' in edge:
            new_left = self._resize_geo.left() + dx
            if geo.right() - new_left >= min_w:
                geo.setLeft(new_left)
        if 'bottom' in edge:
            geo.setBottom(self._resize_geo.bottom() + dy)
        if 'top' in edge:
            new_top = self._resize_geo.top() + dy
            if geo.bottom() - new_top >= min_h:
                geo.setTop(new_top)

        if geo.width() >= min_w and geo.height() >= min_h:
            self.setGeometry(geo)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SpotLrc")
    overlay = SpotLrcOverlay()
    overlay.show()
    overlay._remove_dwm_border()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
