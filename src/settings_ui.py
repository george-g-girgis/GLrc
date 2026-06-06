import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QSlider, QComboBox, QColorDialog, QFormLayout, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from config import save_config

class SettingsDialog(QDialog):
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.setWindowTitle("GLrc Settings")
        self.setFixedSize(420, 480)
        
        # Load icon if available
        base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "myicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.init_ui()
        self.refresh_sources()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # -- Track Info --
        self.track_info_label = QLabel("No track playing")
        self.track_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_info_label.setStyleSheet("font-weight: bold; font-size: 16px; margin-bottom: 5px;")
        layout.addWidget(self.track_info_label)
        
        # -- Media Source Group --
        source_group = QGroupBox("Media Source")
        source_layout = QHBoxLayout()
        
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(150)
        self.source_combo.currentIndexChanged.connect(self.on_source_changed)
        
        self.btn_refresh_source = QPushButton("↻")
        self.btn_refresh_source.setMaximumWidth(30)
        self.btn_refresh_source.clicked.connect(self.refresh_sources)
        
        source_layout.addWidget(QLabel("Listen to:"))
        source_layout.addWidget(self.source_combo, 1)
        source_layout.addWidget(self.btn_refresh_source)
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        
        # -- Display Settings Group --
        display_group = QGroupBox("Display")
        display_layout = QFormLayout()
        display_layout.setSpacing(10)
        
        # Display Mode
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["single", "multi"])
        self.mode_combo.setCurrentText(self.overlay.display_mode)
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        display_layout.addRow("Mode:", self.mode_combo)
        
        # Font Size
        self.font_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_slider.setRange(16, 72)
        self.font_slider.setValue(self.overlay.label_current.font_size)
        self.font_slider.valueChanged.connect(self.on_font_size_changed)
        
        self.font_label = QLabel(str(self.overlay.label_current.font_size))
        font_row = QHBoxLayout()
        font_row.addWidget(self.font_slider)
        font_row.addWidget(self.font_label)
        display_layout.addRow("Font Size:", font_row)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        # -- Color Settings Group --
        color_group = QGroupBox("Colors")
        color_layout = QHBoxLayout()
        
        self.btn_fill = QPushButton("Fill Color")
        self.btn_fill.clicked.connect(self.choose_fill_color)
        
        self.btn_outline = QPushButton("Outline Color")
        self.btn_outline.clicked.connect(self.choose_outline_color)
        
        color_layout.addWidget(self.btn_fill)
        color_layout.addWidget(self.btn_outline)
        color_group.setLayout(color_layout)
        layout.addWidget(color_group)
        
        # -- Sync & Lock Group --
        ctrl_group = QGroupBox("Controls")
        ctrl_layout = QFormLayout()
        ctrl_layout.setSpacing(10)
        
        # Sync Offset
        self.sync_slider = QSlider(Qt.Orientation.Horizontal)
        self.sync_slider.setRange(-5000, 5000)
        self.sync_slider.setSingleStep(100)
        self.sync_slider.setValue(self.overlay.engine.sync_offset_ms)
        self.sync_slider.valueChanged.connect(self.on_sync_changed)
        
        self.sync_label = QLabel(f"{self.overlay.engine.sync_offset_ms} ms")
        self.sync_label.setMinimumWidth(60)
        sync_row = QHBoxLayout()
        sync_row.addWidget(self.sync_slider)
        sync_row.addWidget(self.sync_label)
        ctrl_layout.addRow("Sync Offset:", sync_row)
        
        # Lock Mode
        self.btn_lock = QPushButton("Unlock Overlay" if self.overlay.locked else "Lock Overlay")
        self.btn_lock.clicked.connect(self.toggle_lock)
        ctrl_layout.addRow("Interaction:", self.btn_lock)
        
        ctrl_group.setLayout(ctrl_layout)
        layout.addWidget(ctrl_group)
        
        layout.addStretch()
        
        # -- Footer --
        footer_layout = QVBoxLayout()
        footer_layout.setSpacing(2)
        
        lbl_version = QLabel("Version 2.0")
        lbl_version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_version.setStyleSheet("color: gray; font-size: 11px;")
        
        lbl_powered = QLabel("Powered by GGG")
        lbl_powered.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_powered.setStyleSheet("color: gray; font-size: 11px; font-weight: bold;")
        
        footer_layout.addWidget(lbl_version)
        footer_layout.addWidget(lbl_powered)
        layout.addLayout(footer_layout)

    def update_track_info(self, track_name: str, artist_name: str):
        if track_name and artist_name:
            self.track_info_label.setText(f"🎵 {track_name} — {artist_name}")
        else:
            self.track_info_label.setText("No track playing")

    def refresh_sources(self):
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        
        self.source_combo.addItem("Auto (Any)", userData=None)
        
        sessions = self.overlay.engine.get_available_sessions()
        for clean_name, app_id in sessions:
            self.source_combo.addItem(clean_name, userData=app_id)
            
        target = self.overlay.engine.target_app_id
        idx = 0
        if target:
            for i in range(1, self.source_combo.count()):
                if self.source_combo.itemData(i) == target:
                    idx = i
                    break
        self.source_combo.setCurrentIndex(idx)
        self.source_combo.blockSignals(False)

    def on_source_changed(self, idx: int):
        if idx < 0:
            return
        target = self.source_combo.itemData(idx)
        self.overlay.engine.target_app_id = target
        
        self.overlay.cfg["target_app_id"] = target
        save_config(self.overlay.cfg)
        
        # Force a refresh of the track
        self.overlay.engine.current_track_id = None
        self.overlay.engine._session = None

    def on_mode_changed(self, idx: int):
        mode = "single" if idx == 0 else "multi"
        self.overlay.display_mode = mode
        self.overlay.cfg["display_mode"] = mode
        save_config(self.overlay.cfg)
        
        if mode == "single":
            self.overlay.label_prev.hide()
            self.overlay.label_next.hide()
        else:
            self.overlay.label_prev.show()
            self.overlay.label_next.show()
        
    def on_font_size_changed(self, val: int):
        self.font_label.setText(str(val))
        self.overlay._set_all_font_sizes(val)
        self.overlay.cfg["font_size"] = val
        save_config(self.overlay.cfg)
        
    def choose_fill_color(self):
        original = self.overlay.label_current._fill_color
        dialog = QColorDialog(original, self)
        dialog.setWindowTitle("Choose Text Color")
        
        # Real-time updates
        dialog.currentColorChanged.connect(
            lambda c: self.overlay.set_colors(c, self.overlay.label_current._outline_color)
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            color = dialog.selectedColor()
            self.overlay.set_colors(color, self.overlay.label_current._outline_color)
            self.overlay._save_state()
            self.btn_fill.setStyleSheet(f"background-color: {color.name()}; min-width: 60px; border: 1px solid gray;")
        else:
            # Revert to original if cancelled
            self.overlay.set_colors(original, self.overlay.label_current._outline_color)
            
    def choose_outline_color(self):
        original = self.overlay.label_current._outline_color
        dialog = QColorDialog(original, self)
        dialog.setWindowTitle("Choose Outline Color")
        
        # Real-time updates
        dialog.currentColorChanged.connect(
            lambda c: self.overlay.set_colors(self.overlay.label_current._fill_color, c)
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            color = dialog.selectedColor()
            self.overlay.set_colors(self.overlay.label_current._fill_color, color)
            self.overlay._save_state()
            self.btn_outline.setStyleSheet(f"background-color: {color.name()}; min-width: 60px; border: 1px solid gray;")
        else:
            # Revert to original if cancelled
            self.overlay.set_colors(self.overlay.label_current._fill_color, original)

    def on_sync_changed(self, val: int):
        self.overlay.engine.sync_offset_ms = val
        sign = "+" if val > 0 else ""
        text_val = f"{sign}{val} ms"
        self.sync_label.setText(text_val)
        self.overlay.show_temp_message(f"Sync Offset: {text_val}")
        
    def toggle_lock(self):
        if self.overlay.locked:
            self.overlay.set_edit_mode()
            self.btn_lock.setText("Lock Overlay")
        else:
            self.overlay.set_lock_mode()
            self.btn_lock.setText("Unlock Overlay")
