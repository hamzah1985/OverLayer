import copy
import ctypes
from ctypes import wintypes as W
import json
import logging
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QEvent,
    QLockFile,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from . import keys
from .geometry import ASPECTS, GUIDES, guide_paths
from .overlay import Overlay
from .picker import AreaPicker
from .settings import DEFAULTS, SECTIONS, Store, data_dir, validated
from . import windows as win
from . import taskbar

STYLE = """
QWidget { background: #111923; color: #e7edf2; font-family: 'Segoe UI'; font-size: 12px; }
QLabel#title { font-size: 22px; font-weight: 650; letter-spacing: -0.5px; }
QLabel#muted { color: #93a6b7; }
QLabel#mode { color: #9bddd2; padding: 8px 10px; background: #1a3035; border-radius: 6px; font-weight: 600; }
QLabel#mode[locked="true"] { color: #101923; background: #e9bd78; }
QLabel#status { color: #e9bd78; padding: 0 2px; }
QLabel#warn { color: #e9bd78; }
QPushButton { background: #223243; border: 1px solid #35485a; border-radius: 5px; padding: 7px 10px; }
QPushButton:hover { background: #30465b; border-color: #6b879f; }
QPushButton:focus { border-color: #9bddd2; }
QPushButton:disabled { color: #5d6f80; background: #19232e; border-color: #263442; }
QPushButton:checked { color: #101923; background: #e9bd78; border-color: #e9bd78; }
QPushButton#primary { color: #101923; background: #e9bd78; font-weight: 700; padding: 11px; }
QPushButton#primary:hover { background: #f2cc90; }
QPushButton#ghost { background: transparent; color: #b2c5d4; padding: 5px 10px; }
QPushButton#ghost:hover { background: #1c2a38; }
QPushButton#danger { background: transparent; color: #b2c5d4; padding: 5px 10px; }
QPushButton#danger:hover { background: #3a1f27; border-color: #e0707a; color: #ffb3b8; }
QPushButton#section { text-align: left; background: transparent; border: none; border-bottom: 1px solid #2a3948; border-radius: 0; padding: 10px 4px 8px; font-weight: 700; color: #b2c5d4; }
QPushButton#section:hover { color: #e9bd78; }
QPushButton#section:focus { border-bottom-color: #9bddd2; }
QPushButton#swatch { padding: 0; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #1a2734; border: 1px solid #35485a; padding: 5px; border-radius: 4px; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border-color: #9bddd2; }
QComboBox QAbstractItemView { selection-background-color: #354c61; }
QSlider::groove:horizontal { height: 4px; background: #324558; border-radius: 2px; }
QSlider::handle:horizontal { background: #e9bd78; width: 12px; margin: -4px 0; border-radius: 6px; }
QSlider::handle:horizontal:focus { background: #9bddd2; }
QScrollArea { border: none; }
QToolTip { color: #eef3f7; background: #26394a; border: 1px solid #61768a; }
"""

SWATCHES = ("#000000", "#ffffff", "#e9bd78", "#9bddd2", "#ff5a5f")
# Executable-name prefixes of creative apps, pre-selected in the window list.
KNOWN_HOSTS = (
    "d5",
    "blender",
    "sketchup",
    "unrealeditor",
    "3dsmax",
    "maya",
    "photoshop",
    "lumion",
    "twinmotion",
    "houdini",
    "cinema4d",
    "rhino",
    "revit",
    "archicad",
    "keyshot",
    "enscape",
)
EXE_ROLE = Qt.ItemDataRole.UserRole + 1


def app_icon(locked=False):
    pix = QPixmap(64, 64)
    pix.fill(QColor("#111923"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#e9bd78"), 3))
    p.drawRoundedRect(10, 10, 44, 44, 7, 7)
    for n in (25, 39):
        p.drawLine(n, 12, n, 52)
        p.drawLine(12, n, 52, n)
    p.setPen(QPen(QColor("#9bddd2"), 3))
    p.drawEllipse(35, 21, 8, 8)
    if locked:
        # Small padlock so the notification-area icon shows the lock state.
        p.setPen(QPen(QColor("#111923"), 2))
        p.setBrush(QColor("#e9bd78"))
        p.drawRoundedRect(QRectF(34, 36, 24, 20), 4, 4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#e9bd78"), 4))
        p.drawArc(QRectF(38, 24, 16, 20), 0, 180 * 16)
    p.end()
    return QIcon(pix)


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class GuideChip(QAbstractButton):
    """Checkable guide tile with a live miniature of its lines."""

    def __init__(self, key, title):
        super().__init__()
        self.key = key
        self.title = title
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(title)
        self.setAccessibleName(title)
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.paths = guide_paths(key, 4, 3, DEFAULTS)
        # Modifier keys of the latest press: Shift/Ctrl add to the selection.
        self.modifiers = Qt.KeyboardModifier.NoModifier

    def mousePressEvent(self, event):
        self.modifiers = event.modifiers()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        self.modifiers = event.modifiers()
        super().keyPressEvent(event)

    def take_modifiers(self):
        modifiers, self.modifiers = self.modifiers, Qt.KeyboardModifier.NoModifier
        return modifiers

    def sizeHint(self):
        return QSize(150, 48)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked, hover = self.isChecked(), self.underMouse()
        accent = QColor("#e9bd78")
        outline = accent if checked else QColor("#6b879f" if hover else "#35485a")
        p.setPen(QPen(outline, 1.5 if checked else 1))
        p.setBrush(QColor("#2c2a24" if checked else "#223243" if hover else "#1a2734"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 7, 7)
        thumb = QRectF(8, 8, 44, 33)
        p.setPen(QPen(QColor("#2a3948"), 1))
        p.setBrush(QColor("#0e1620"))
        p.drawRect(thumb)
        p.save()
        p.setClipRect(thumb)
        p.setPen(QPen(accent if checked else QColor("#93a6b7"), 1))
        for points in self.paths:
            path = QPainterPath()
            for i, (x, y) in enumerate(points):
                pt = QPointF(
                    thumb.x() + x * thumb.width(), thumb.y() + y * thumb.height()
                )
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.drawPath(path)
        p.restore()
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#f2e3c8" if checked else "#c5d3df"))
        p.drawText(
            QRectF(60, 2, self.width() - 66, self.height() - 4),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            | int(Qt.TextFlag.TextWordWrap),
            self.title,
        )
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#9bddd2"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        p.end()


class Check(QCheckBox):
    """Check box with a visible tick and keyboard focus ring."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        box = QRectF(0.5, (self.height() - 15) / 2 + 0.5, 14, 14)
        if self.isChecked():
            p.setPen(QPen(QColor("#e9bd78"), 1))
            p.setBrush(QColor("#e9bd78"))
        else:
            p.setPen(QPen(QColor("#566b7e"), 1))
            p.setBrush(QColor("#172330"))
        p.drawRoundedRect(box, 3, 3)
        if self.isChecked():
            p.setPen(QPen(QColor("#101923"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            tick = QPainterPath()
            tick.moveTo(box.x() + 3.5, box.y() + 7.5)
            tick.lineTo(box.x() + 6, box.y() + 10)
            tick.lineTo(box.x() + 10.5, box.y() + 4.5)
            p.drawPath(tick)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#9bddd2"), 2))
            p.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 4, 4)
        p.setPen(QColor("#e7edf2" if enabled else "#5d6f80"))
        p.drawText(
            QRectF(23, 0, self.width() - 23, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
        p.end()


class Section(QWidget):
    """Collapsible titled block of controls."""

    expandedChanged = Signal(bool)

    def __init__(self, title, expanded=True):
        super().__init__()
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)
        self.header = QPushButton()
        self.header.setObjectName("section")
        self.header.setCheckable(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.toggled.connect(self.set_expanded)
        layout.addWidget(self.header)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(4, 12, 4, 8)
        self.content.setSpacing(8)
        layout.addWidget(self.body)
        self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(False)
        self.apply(expanded)

    def apply(self, expanded):
        # "&&": a single ampersand would be eaten as a keyboard-accelerator mark.
        self.header.setText(
            ("▾  " if expanded else "▸  ") + self.title.replace("&", "&&")
        )
        self.body.setVisible(expanded)

    def set_expanded(self, expanded):
        self.apply(expanded)
        self.expandedChanged.emit(expanded)

    def is_expanded(self):
        return self.header.isChecked()


class WindowCombo(QComboBox):
    """Window picker that refreshes its list every time it is opened."""

    about_to_show = Signal()

    def showPopup(self):
        self.about_to_show.emit()
        super().showPopup()


class KeyEdit(QKeySequenceEdit):
    recording = Signal(bool)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.recording.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.recording.emit(False)


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, callbacks, bindings):
        super().__init__()
        self.callbacks = callbacks
        self.registered = []
        self.failed = []
        self.apply(bindings)

    def apply(self, bindings):
        """(Re)register {RegisterHotKey id: shortcut text}."""
        self.close()
        self.failed = []
        for ident, spec in bindings.items():
            parsed = keys.parse(spec)
            # 0x4000 = MOD_NOREPEAT
            if parsed and win.user32.RegisterHotKey(
                None, ident, 0x4000 | parsed[0], parsed[1]
            ):
                self.registered.append(ident)
            else:
                self.failed.append(spec)

    def nativeEventFilter(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == 0x312 and int(msg.wParam) in self.callbacks:
            QTimer.singleShot(0, self.callbacks[int(msg.wParam)])
            return True, 0
        return False, 0

    def close(self):
        for ident in self.registered:
            win.user32.UnregisterHotKey(None, ident)
        self.registered.clear()


class Controller(QWidget):
    def __init__(self, store=None):
        super().__init__(
            None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self._geometry_ready = False
        self.store = store or Store()
        self.state = self.store.state
        self.target = None
        self.target_exe = ""
        self.relative = None
        # A saved locked frame has no attached host after restart. Start it
        # hidden instead of restoring an uneditable overlay over the desktop.
        self.wanted_visible = not self.state["locked"]
        self.syncing = False
        self.quitting = False
        self.picker = None
        self.reset_backup = None
        self.recording_keys = False
        self.sections = {}
        self.key_edits = {}
        self.key_warns = {}
        self._last_client = None
        self._active_until = 0.0
        self._next_auto = 0.0
        self.auto_pending = bool(
            self.store.ui.get("auto_follow") and self.store.ui.get("follow_exe")
        )
        self.setWindowTitle(f"OverLayer {__version__}")
        self.icons = {False: app_icon(), True: app_icon(True)}
        self.setWindowIcon(self.icons[False])
        self.taskbar_configured = False
        self.resize(470, 780)
        self.setMinimumWidth(440)
        self.overlay = Overlay(self.state)
        self.restore_rect()
        self.overlay.edited.connect(self.geometry_edited)
        self.overlay.reference_error.connect(
            lambda name: self.notice(f"Could not read the reference image “{name}”.")
        )
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.clear_notice)
        self.position_restore_timer = QTimer(self)
        self.position_restore_timer.setSingleShot(True)
        self.position_restore_timer.timeout.connect(self.finish_panel_restore)
        self.pending_panel_rect = self.store.ui.get("panel_rect")
        self.overlay.placement_changed.connect(self.overlay_geometry_changed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(22, 18, 22, 16)
        self.body.setSpacing(8)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        self.build_ui()
        self.guard_wheel()
        self.make_tray()
        self.escape_controls = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_controls.activated.connect(self.request_quit)
        self.escape_overlay = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.overlay)
        self.escape_overlay.activated.connect(
            lambda: self.request_quit() if not self.state["locked"] else None
        )
        self.lock_shortcuts = []
        for widget in (self, self.overlay):
            for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                shortcut = QShortcut(QKeySequence(key), widget)
                shortcut.activated.connect(self.lock_overlay)
                self.lock_shortcuts.append(shortcut)
        actions = {
            "toggle_overlay": self.toggle_overlay,
            "toggle_lock": self.toggle_lock,
            "toggle_panel": self.toggle_panel,
            "draw_area": self.draw_area,
            "quit": self.request_quit,
            "hide_overlay": self.hide_overlay,
            "next_preset": lambda: self.cycle_preset(1),
            "prev_preset": lambda: self.cycle_preset(-1),
        }
        self.hotkeys = Hotkeys(
            {ident: actions[name] for ident, name, _, _ in keys.ACTIONS},
            self.store.hotkey_bindings(),
        )
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        risky = self.refresh_hotkey_hints()
        self.follow_timer = QTimer(self)
        self.follow_timer.timeout.connect(self.follow_target)
        self.follow_timer.start(100)
        self.sync_ui()
        self.restore_window_positions()
        try:
            taskbar.configure(int(self.winId()))
            self.taskbar_configured = True
        except OSError:
            logging.exception("Could not configure Windows taskbar identity")
        self.restore_rect()
        self.sync_rect()
        self._geometry_ready = True
        self.try_auto_follow()
        self.follow_target()
        if self.hotkeys.failed:
            self.notice(
                "Shortcut unavailable: "
                + ", ".join(self.hotkeys.failed)
                + ". Change it under Shortcuts or use the tray menu.",
                12000,
            )
        elif self.store.error:
            self.notice(self.store.error, 12000)
        elif risky:
            self.notice(
                ", ".join(risky)
                + " may clash with typing on your keyboard layout (AltGr). "
                "Rebind it under Shortcuts.",
                12000,
            )

    # ------------------------------------------------------------------ UI

    def text(self, value, name=None):
        label = QLabel(value)
        label.setWordWrap(True)
        if name:
            label.setObjectName(name)
        return label

    def section(self, name, title):
        expanded = self.store.ui.get("sections", {}).get(name, SECTIONS[name])
        section = Section(title, expanded)
        section.expandedChanged.connect(
            lambda open_, n=name: self.section_toggled(n, open_)
        )
        self.body.addWidget(section)
        self.sections[name] = section
        return section.content

    def section_toggled(self, name, expanded):
        self.store.ui.setdefault("sections", {})[name] = expanded
        self.schedule_save()

    def button(self, label, callback, name=None):
        button = QPushButton(label)
        button.clicked.connect(callback)
        if name:
            button.setObjectName(name)
        return button

    def slider(self, low, high, key):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.valueChanged.connect(lambda v: self.change(key, v))
        return slider

    def build_ui(self):
        row = QHBoxLayout()
        row.addWidget(self.text("OverLayer", "title"))
        row.addWidget(self.text(f"v{__version__}", "muted"))
        row.addStretch()
        quit_button = self.button("Quit…", self.request_quit, "danger")
        quit_button.setToolTip("Remove the overlay and exit OverLayer")
        row.addWidget(quit_button)
        self.body.addLayout(row)
        self.mode = self.text("", "mode")
        self.body.addWidget(self.mode)
        row = QHBoxLayout()
        self.status = self.text("", "status")
        self.status.setMinimumHeight(32)
        self.status.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.undo_button = self.button("Undo", self.undo_reset, "ghost")
        self.undo_button.hide()
        row.addWidget(self.status, 1)
        row.addWidget(self.undo_button)
        self.body.addLayout(row)
        row = QHBoxLayout()
        self.lock_button = self.button("Lock overlay", self.toggle_lock, "primary")
        self.show_button = self.button("Hide guides", self.toggle_overlay)
        row.addWidget(self.lock_button, 2)
        row.addWidget(self.show_button, 1)
        self.body.addLayout(row)
        self.hint = self.text("", "muted")
        self.body.addWidget(self.hint)
        row = QHBoxLayout()
        row.addWidget(self.button("Draw viewport area…", self.draw_area), 3)
        hide_button = self.button("Hide controls", self.hide)
        hide_button.setToolTip("Close this panel; the guides keep running")
        row.addWidget(hide_button, 1)
        self.body.addLayout(row)
        self.body.addWidget(
            self.text(
                "Draw your viewport, then drag the dots to fine-tune it "
                "(Shift = precise, arrow keys nudge). Press Enter to lock.",
                "muted",
            )
        )

        layout = self.section("guides", "01   COMPOSITION GUIDES")
        grid = QGridLayout()
        grid.setSpacing(6)
        self.guide_boxes = {}
        for index, (key, title) in enumerate(GUIDES.items()):
            chip = GuideChip(key, title)
            chip.clicked.connect(lambda _=False, c=chip: self.guide_clicked(c))
            grid.addWidget(chip, index // 2, index % 2)
            self.guide_boxes[key] = chip
        layout.addLayout(grid)
        layout.addWidget(
            self.text(
                "Click a guide to use it alone; Shift+click adds more. In "
                "alignment mode, drag the teal dots to place vanishing points "
                "and the focal point.",
                "muted",
            )
        )
        row = QHBoxLayout()
        self.flip_h = self.button("Flip ↔", lambda: self.flip("flip_h"))
        self.flip_h.setCheckable(True)
        self.flip_v = self.button("Flip ↕", lambda: self.flip("flip_v"))
        self.flip_v.setCheckable(True)
        self.rotate_button = self.button("Rotate 90°", self.rotate)
        row.addWidget(self.flip_h)
        row.addWidget(self.flip_v)
        row.addWidget(self.rotate_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Custom grid"))
        self.columns = QSpinBox()
        self.columns.setRange(2, 16)
        self.columns.valueChanged.connect(lambda v: self.change("columns", v))
        self.rows = QSpinBox()
        self.rows.setRange(2, 16)
        self.rows.valueChanged.connect(lambda v: self.change("rows", v))
        row.addWidget(self.columns)
        row.addWidget(QLabel("×"))
        row.addWidget(self.rows)
        layout.addLayout(row)

        layout = self.section("frame", "02   FRAME & APPEARANCE")
        form = self.frame_form = QFormLayout()
        self.aspect = QComboBox()
        self.aspect.addItems(ASPECTS)
        self.aspect.currentTextChanged.connect(lambda v: self.change("aspect", v))
        form.addRow("Crop frame", self.aspect)
        self.custom_row = QWidget()
        custom = QHBoxLayout(self.custom_row)
        custom.setContentsMargins(0, 0, 0, 0)
        self.custom_w = QSpinBox()
        self.custom_w.setRange(1, 999)
        self.custom_w.valueChanged.connect(lambda v: self.change("custom_w", v))
        self.custom_h = QSpinBox()
        self.custom_h.setRange(1, 999)
        self.custom_h.valueChanged.connect(lambda v: self.change("custom_h", v))
        custom.addWidget(self.custom_w)
        custom.addWidget(QLabel(":"))
        custom.addWidget(self.custom_h)
        custom.addStretch()
        form.addRow("Custom ratio", self.custom_row)
        colors = QHBoxLayout()
        colors.setSpacing(6)
        self.swatches = {}
        for color in SWATCHES:
            swatch = self.button(
                "", lambda _=False, c=color: self.set_color(c), "swatch"
            )
            swatch.setFixedSize(26, 26)
            swatch.setToolTip(color.upper())
            colors.addWidget(swatch)
            self.swatches[color] = swatch
        self.color_button = self.button("Custom…", self.pick_color)
        colors.addWidget(self.color_button, 1)
        form.addRow("Line color", colors)
        self.opacity = self.slider(10, 100, "opacity")
        form.addRow("Guide opacity", self.opacity)
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0.5, 6)
        self.thickness.setSingleStep(0.25)
        self.thickness.setSuffix(" px")
        self.thickness.valueChanged.connect(lambda v: self.change("thickness", v))
        form.addRow("Line thickness", self.thickness)
        self.margin_pct = QSpinBox()
        self.margin_pct.setRange(1, 25)
        self.margin_pct.setSuffix(" %")
        self.margin_pct.valueChanged.connect(lambda v: self.change("margin_pct", v))
        form.addRow("Safe margin", self.margin_pct)
        layout.addLayout(form)
        grid = QGridLayout()
        self.extras = {}
        for index, (key, title, tip) in enumerate(
            (
                ("border", "Frame edge", "Draw an outline around the frame"),
                ("margins", "Safe area", "Dashed safe-margin rectangle"),
                ("focal", "Focal point", "Draggable focal-point marker"),
                (
                    "halo",
                    "Contrast halo",
                    "Draw a thin light or dark outline under each line so "
                    "guides stay visible on any image",
                ),
                (
                    "dim_outside",
                    "Dim outside crop",
                    "Darken the area outside a crop frame",
                ),
            )
        ):
            box = Check(title)
            box.setToolTip(tip)
            box.toggled.connect(lambda v, k=key: self.change(k, v))
            self.extras[key] = box
            grid.addWidget(box, index // 2, index % 2)
        layout.addLayout(grid)

        layout = self.section("follow", "03   ALIGN & FOLLOW")
        self.window_list = WindowCombo()
        self.window_list.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.window_list.setMinimumContentsLength(20)
        self.window_list.about_to_show.connect(self.refresh_windows)
        layout.addWidget(self.window_list)
        row = QHBoxLayout()
        self.attach_button = self.button("Follow window", self.attach)
        self.match_button = self.button("Match window", self.match_window)
        self.match_button.setToolTip("Fit the frame to the followed window's content area")
        self.match_button.setEnabled(False)
        row.addWidget(self.attach_button)
        row.addWidget(self.match_button)
        layout.addLayout(row)
        self.target_label = self.text("Free placement · no window attached", "muted")
        layout.addWidget(self.target_label)
        layout.addWidget(
            self.text(
                "Pick your app, then follow it. Your frame keeps its relative "
                "position and size, and stays visible while any window of that "
                "app is in front.",
                "muted",
            )
        )
        self.auto_follow_box = Check("Follow this app automatically next time")
        self.auto_follow_box.setToolTip(
            "On launch, attach to the app you last followed and restore the frame"
        )
        self.auto_follow_box.toggled.connect(self.auto_follow_toggled)
        layout.addWidget(self.auto_follow_box)
        row = QHBoxLayout()
        row.addWidget(self.button("Fit screen", self.fit_screen))
        row.addWidget(self.button("Reset points", self.reset_points))
        layout.addLayout(row)
        grid = QGridLayout()
        self.rect_fields = []
        for index, title in enumerate(("X", "Y", "Width", "Height")):
            spin = QSpinBox()
            spin.setRange(-32000, 32000) if index < 2 else spin.setRange(
                240 if index == 2 else 180, 16000
            )
            spin.setMinimumWidth(55)
            spin.setMaximumWidth(90)
            spin.valueChanged.connect(self.rect_changed)
            grid.addWidget(QLabel(title), 0, index)
            grid.addWidget(spin, 1, index)
            self.rect_fields.append(spin)
        layout.addLayout(grid)

        layout = self.section("refs", "04   REFERENCES & PRESETS")
        row = QHBoxLayout()
        row.addWidget(self.button("Reference image…", self.load_reference))
        row.addWidget(self.button("Clear", lambda: self.change("reference", "")))
        layout.addLayout(row)
        self.reference_label = self.text("No reference image", "muted")
        layout.addWidget(self.reference_label)
        form = QFormLayout()
        self.ref_opacity = self.slider(0, 100, "reference_opacity")
        self.ref_scale = self.slider(10, 400, "reference_scale")
        self.ref_dx = self.slider(-100, 100, "reference_dx")
        self.ref_dy = self.slider(-100, 100, "reference_dy")
        form.addRow("Opacity", self.ref_opacity)
        form.addRow("Scale", self.ref_scale)
        form.addRow("Offset X", self.ref_dx)
        form.addRow("Offset Y", self.ref_dy)
        layout.addLayout(form)
        self.presets = QComboBox()
        self.presets.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.presets.setMinimumContentsLength(20)
        self.refresh_presets()
        layout.addWidget(self.presets)
        row = QHBoxLayout()
        for label, callback in (
            ("Save preset…", self.save_preset),
            ("Load", self.load_preset),
            ("Delete", self.delete_preset),
        ):
            row.addWidget(self.button(label, callback))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.button("Export preset…", self.export_preset))
        row.addWidget(self.button("Import preset…", self.import_preset))
        layout.addLayout(row)

        layout = self.section("keys", "05   SHORTCUTS")
        layout.addWidget(
            self.text(
                "Click a box and press the new combination: Ctrl, Alt, Shift or "
                "Win plus a key. Shortcuts work from any application.",
                "muted",
            )
        )
        grid = QGridLayout()
        for index, (_, name, label, _) in enumerate(keys.ACTIONS):
            edit = KeyEdit()
            edit.setMaximumSequenceLength(1)
            edit.setToolTip(f"Shortcut: {label}")
            edit.editingFinished.connect(lambda n=name: self.hotkey_edited(n))
            edit.recording.connect(self.hotkey_recording)
            warn = self.text("", "warn")
            grid.addWidget(QLabel(label), index * 2, 0)
            grid.addWidget(edit, index * 2, 1)
            grid.addWidget(warn, index * 2 + 1, 0, 1, 2)
            warn.hide()
            self.key_edits[name] = edit
            self.key_warns[name] = warn
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addWidget(self.button("Restore default shortcuts", self.restore_hotkeys))
        layout.addWidget(
            self.text(
                "Also: Enter locks the overlay · Esc offers to quit · "
                "arrow keys nudge an unlocked frame (Shift ×10, Ctrl resizes).",
                "muted",
            )
        )

        row = QHBoxLayout()
        self.saved_label = self.text("Changes save automatically", "muted")
        row.addWidget(self.saved_label, 1)
        reset = self.button("Reset appearance", self.reset_setup, "ghost")
        reset.setToolTip(
            "Reset guides and appearance; keep viewport placement and named presets"
        )
        row.addWidget(reset)
        self.body.addSpacing(6)
        self.body.addLayout(row)
        self.body.addWidget(
            self.text(
                f"OverLayer {__version__} by Bogdan Demchenko · Closing hides "
                "unattached guides. Quit removes the overlay and exits.",
                "muted",
            )
        )
        self.body.addStretch()
        self.sync_hotkey_edits()
        self.refresh_windows()

    def guard_wheel(self):
        """Let the mouse wheel scroll the panel instead of changing a control."""
        for kind in (QAbstractSlider, QAbstractSpinBox, QComboBox):
            for widget in self.content.findChildren(kind):
                widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.Wheel
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            # Ctrl+wheel still adjusts the hovered control on purpose.
            QApplication.sendEvent(self.scroll.verticalScrollBar(), event)
            return True
        return super().eventFilter(obj, event)

    def make_tray(self):
        self.tray = QSystemTrayIcon(self.icons[False], self)
        menu = QMenu(self)
        for title, callback in (
            ("Show controls", self.show_panel),
            ("Draw viewport area…", self.draw_area),
            ("Lock / unlock overlay", self.toggle_lock),
            ("Show / hide guides", self.toggle_overlay),
            ("Hide guides now", self.hide_overlay),
            ("Next preset", lambda: self.cycle_preset(1)),
            ("Previous preset", lambda: self.cycle_preset(-1)),
        ):
            action = menu.addAction(title)
            action.triggered.connect(callback)
        menu.addSeparator()
        menu.addAction("Quit OverLayer…").triggered.connect(self.request_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_panel()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    # ------------------------------------------------------------ messages

    def notice(self, message, ms=5000, undo=False):
        """Show a transient message under the mode banner."""
        self.status.setText(message)
        self.undo_button.setVisible(undo)
        self.notice_timer.start(ms)

    def clear_notice(self):
        self.status.clear()
        self.undo_button.hide()
        self.reset_backup = None

    def refresh_mode(self):
        locked = self.state["locked"]
        self.mode.setText(
            "LOCKED · clicks pass through to your app"
            if locked
            else "ALIGNMENT MODE · position your frame"
        )
        self.mode.setProperty("locked", locked)
        repolish(self.mode)

    # -------------------------------------------------------------- state

    def change(self, key, value):
        if self.syncing:
            return
        self.state[key] = value
        self.overlay.update()
        self.schedule_save()
        if key == "reference":
            self.reference_label.setText(
                Path(value).name if value else "No reference image"
            )
        elif key == "aspect":
            self.show_custom_ratio(value == "Custom")

    def show_custom_ratio(self, visible):
        # Hide label and field together so no orphan "Custom ratio" caption stays.
        self.frame_form.setRowVisible(self.custom_row, visible)

    def guide_clicked(self, chip):
        """One guide at a time; Shift- or Ctrl-click adds or removes extras."""
        if self.syncing:
            return
        key = chip.key
        guides = list(self.state["guides"])
        additive = chip.take_modifiers() & (
            Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier
        )
        if additive:
            guides = [g for g in guides if g != key] if key in guides else guides + [key]
        else:
            # Clicking the only active guide switches it off.
            guides = [] if guides == [key] else [key]
        self.state["guides"] = guides
        self.overlay.update()
        self.schedule_save()
        self.sync_ui()

    def flip(self, key):
        self.change(key, not self.state[key])
        self.sync_ui()

    def rotate(self):
        self.change("rotation", (self.state["rotation"] + 1) % 4)
        self.sync_ui()

    def set_color(self, color):
        self.change("color", color)
        self.sync_ui()

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.state["color"]), self, "Guide color")
        if color.isValid():
            self.set_color(color.name())

    def toggle_lock(self):
        self.overlay.set_locked(not self.state["locked"])
        self.sync_ui()
        self.schedule_save()

    def lock_overlay(self):
        if self.quitting or self.picker is not None or not self.wanted_visible:
            return
        if not self.state["locked"]:
            self.overlay.set_locked(True)
            self.sync_ui()
            self.schedule_save()

    def toggle_overlay(self):
        self.wanted_visible = not self.wanted_visible
        self.follow_target()
        self.sync_ui()

    def hide_overlay(self):
        if self.picker is not None:
            self.picker.finish(None)
        self.wanted_visible = False
        self.overlay.hide()
        self.sync_ui()
        self.notice("Guides hidden · Show guides to bring them back")

    def nativeEvent(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == win.SHOW_CONTROLS_MESSAGE:
            QTimer.singleShot(0, self.show_panel)
            return True, 0
        return super().nativeEvent(event_type, message)

    def show_panel(self):
        if self.quitting:
            return
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        if self.pending_panel_rect is not None:
            # The first show completes Windows' DPI/non-client frame setup.
            # Reapply saved client bounds afterwards to avoid frame-size drift.
            self.position_restore_timer.start(20)
        self.keep_panel_visible()
        self.raise_()
        self.activateWindow()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.recording_keys:
            # Never leave global shortcuts unregistered after a half-finished edit.
            self.hotkey_recording(False)

    def finish_panel_restore(self):
        if self.quitting or self.pending_panel_rect is None:
            return
        rect = self.pending_panel_rect
        self.pending_panel_rect = None
        if not self.isMaximized():
            self.setGeometry(*rect)
            self.keep_panel_visible()

    def keep_panel_visible(self):
        screen = (
            QApplication.screenAt(self.geometry().center())
            or QApplication.primaryScreen()
        )
        area = screen.availableGeometry()
        if not self.isMaximized():
            width, height = (
                min(self.width(), area.width() - 20),
                min(self.height(), max(300, area.height() - 36)),
            )
            if width != self.width() or height != self.height():
                self.resize(width, height)
            frame = self.frameGeometry()
            if not area.contains(frame):
                self.move(
                    max(area.left(), min(frame.x(), area.right() - frame.width() + 1)),
                    max(area.top(), min(frame.y(), area.bottom() - frame.height() + 1)),
                )

    def toggle_panel(self):
        self.hide() if self.isVisible() and not self.isMinimized() else self.show_panel()

    def draw_area(self):
        if self.quitting:
            return
        if self.picker is not None:
            self.picker.raise_()
            self.picker.activateWindow()
            return
        self.panel_before_pick = self.isVisible()
        self.overlay.hide()
        self.picker = AreaPicker()
        self.picker.finished.connect(self.area_picked)
        self.picker.show()
        self.hide()
        self.picker.raise_()
        self.picker.activateWindow()
        self.picker.setFocus()

    def area_picked(self, rect):
        self.picker = None
        if rect is not None:
            if rect.width() < 240 or rect.height() < 180:
                self.notice("Draw an area at least 240 × 180 pixels.")
            else:
                self.overlay.setGeometry(rect)
                self.overlay.set_locked(False)
                self.wanted_visible = True
                self.geometry_edited()
                self.sync_ui()
        if self.panel_before_pick:
            self.show_panel()
        self.follow_target()

    def closeEvent(self, event):
        event.ignore()
        if not self.target:
            self.hide_overlay()
        self.hide()
        self.save()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # Keep controls recoverable on systems without a notification area.
            self.showMinimized()

    def restore_rect(self):
        rect = self.overlay.geometry()
        if not any(
            screen.availableGeometry().intersects(rect)
            for screen in QApplication.screens()
        ):
            area = QApplication.primaryScreen().availableGeometry()
            rect.moveTopLeft(area.topLeft())
            self.overlay.setGeometry(rect)

    def restore_window_positions(self):
        for key, widget, rect in (
            ("panel_screen", self, self.store.ui.get("panel_rect")),
            ("overlay_screen", self.overlay, self.state["rect"]),
        ):
            if not rect:
                continue
            screen = next(
                (
                    screen
                    for screen in QApplication.screens()
                    if screen.name() == self.store.ui.get(key)
                ),
                None,
            )
            if screen is None:
                screen = (
                    QApplication.screenAt(QRect(*rect).center())
                    or QApplication.primaryScreen()
                )
            # Select the monitor before assigning logical client bounds, avoiding
            # Windows rescaling the non-client frame during restoreGeometry.
            widget.winId()
            widget.windowHandle().setScreen(screen)
            widget.setGeometry(*rect)
        if self.store.ui.get("panel_maximized"):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def sync_ui(self):
        self.syncing = True
        for key, box in self.guide_boxes.items():
            box.setChecked(key in self.state["guides"])
        for key, widget in (
            ("opacity", self.opacity),
            ("reference_opacity", self.ref_opacity),
            ("reference_scale", self.ref_scale),
            ("reference_dx", self.ref_dx),
            ("reference_dy", self.ref_dy),
            ("thickness", self.thickness),
            ("rows", self.rows),
            ("columns", self.columns),
            ("custom_w", self.custom_w),
            ("custom_h", self.custom_h),
            ("margin_pct", self.margin_pct),
        ):
            widget.setValue(self.state[key])
        for key, box in self.extras.items():
            box.setChecked(self.state[key])
        self.aspect.setCurrentText(self.state["aspect"])
        self.show_custom_ratio(self.state["aspect"] == "Custom")
        self.flip_h.setChecked(self.state["flip_h"])
        self.flip_v.setChecked(self.state["flip_v"])
        self.rotate_button.setText(f"Rotate · {self.state['rotation'] * 90}°")
        locked = self.state["locked"]
        self.lock_button.setText("Unlock to align" if locked else "Lock overlay")
        self.show_button.setText(
            "Hide guides" if self.wanted_visible else "Show guides"
        )
        current = self.state["color"].lower()
        for color, swatch in self.swatches.items():
            swatch.setStyleSheet(
                f"background: {color}; border-radius: 13px; border: 2px solid "
                f"{'#9bddd2' if color == current else '#35485a'};"
            )
        custom = current not in self.swatches
        foreground = "#ffffff" if QColor(current).lightness() < 128 else "#111923"
        self.color_button.setText(f"Custom · {current.upper()}" if custom else "Custom…")
        self.color_button.setStyleSheet(
            f"background: {current}; color: {foreground}; border: 2px solid #9bddd2;"
            if custom
            else ""
        )
        self.auto_follow_box.setChecked(bool(self.store.ui.get("auto_follow")))
        self.reference_label.setText(
            Path(self.state["reference"]).name
            if self.state["reference"]
            else "No reference image"
        )
        self.sync_rect()
        self.refresh_mode()
        self.tray.setIcon(self.icons[locked])
        self.tray.setToolTip(
            "OverLayer · " + ("locked" if locked else "alignment mode")
            + f" · {self.store.hotkeys['toggle_panel']} for controls"
        )
        self.syncing = False

    def sync_rect(self):
        rect = self.overlay.geometry()
        for spin, value in zip(
            self.rect_fields, (rect.x(), rect.y(), rect.width(), rect.height())
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def rect_changed(self):
        if self.syncing:
            return
        self.overlay.setGeometry(*(field.value() for field in self.rect_fields))
        self.geometry_edited()

    def geometry_edited(self):
        self.sync_rect()
        self.capture_relative()
        self.schedule_save()

    def fit_screen(self):
        screen = (
            QApplication.screenAt(self.overlay.geometry().center())
            or QApplication.primaryScreen()
        )
        self.overlay.setGeometry(screen.availableGeometry().adjusted(60, 60, -60, -60))
        self.geometry_edited()

    def match_window(self):
        rect = self.logical_client_rect() if self.target else None
        if not rect:
            self.notice("Follow an open window first, then match it.")
            return
        x, y, w, h = rect
        self.overlay.setGeometry(
            round(x), round(y), max(240, round(w)), max(180, round(h))
        )
        self.geometry_edited()
        self.notice("Frame matched to the window's content area")

    def reset_points(self):
        for key in ("vp", "left_vp", "right_vp", "focus"):
            self.state[key] = copy.deepcopy(DEFAULTS[key])
        self.overlay.update()
        self.schedule_save()

    # ----------------------------------------------------- window following

    def refresh_windows(self):
        selected = self.window_list.currentData()
        entries = win.windows()
        self.window_list.clear()
        known = -1
        for hwnd, title, exe in entries:
            self.window_list.addItem(f"{title}  —  {exe}" if exe else title, hwnd)
            index = self.window_list.count() - 1
            self.window_list.setItemData(index, exe, EXE_ROLE)
            if known < 0 and exe.lower().startswith(KNOWN_HOSTS):
                known = index
        index = self.window_list.findData(selected)
        if index >= 0:
            self.window_list.setCurrentIndex(index)
        elif known >= 0:
            self.window_list.setCurrentIndex(known)

    def attach(self):
        if self.target:
            self.detach()
            return
        hwnd = self.window_list.currentData()
        if not hwnd or not win.client_rect(hwnd):
            self.notice("Choose an open, non-minimized window, then follow it.")
            return
        self.begin_follow(
            hwnd,
            self.window_list.currentText(),
            self.window_list.currentData(EXE_ROLE) or "",
        )

    def begin_follow(self, hwnd, title, exe, relative=None):
        self.target = hwnd
        self.target_exe = exe
        self.auto_pending = False
        if relative:
            self.relative = tuple(relative)
        else:
            self.capture_relative()
        self.remember_follow()
        self.attach_button.setText("Detach window")
        self.match_button.setEnabled(True)
        self.target_label.setText(
            "Following: " + title[:90] + ("…" if len(title) > 90 else "")
        )
        self.follow_target()

    def detach(self, manual=True):
        self.target = None
        self.target_exe = ""
        self.relative = None
        # A window that merely closed may come back; an explicit detach is final.
        self.auto_pending = not manual and bool(
            self.store.ui.get("auto_follow") and self.store.ui.get("follow_exe")
        )
        self.attach_button.setText("Follow window")
        self.match_button.setEnabled(False)
        self.target_label.setText("Free placement · no window attached")
        self.follow_target()

    def remember_follow(self):
        if self.store.ui.get("auto_follow") and self.target_exe:
            self.store.ui["follow_exe"] = self.target_exe
            self.schedule_save()

    def auto_follow_toggled(self, checked):
        if self.syncing:
            return
        self.store.ui["auto_follow"] = checked
        self.remember_follow()
        self.schedule_save()

    def try_auto_follow(self):
        """Attach to the app followed last time, once it has a usable window."""
        exe = self.store.ui.get("follow_exe", "").lower()
        if not (self.store.ui.get("auto_follow") and exe) or self.target:
            return False
        best = None
        for hwnd, title, name in win.windows():
            if name.lower() != exe:
                continue
            rect = win.client_rect(hwnd)
            area = rect[2] * rect[3] if rect else 0
            if area >= 300 * 200 and (best is None or area > best[0]):
                best = (area, hwnd, title, name)
        if best is None:
            return False
        _, hwnd, title, name = best
        saved = self.store.ui.get("relative")
        self.begin_follow(hwnd, title, name, saved)
        # An attached host makes a saved locked frame safe to restore.
        self.wanted_visible = True
        self.sync_ui()
        return True

    def logical_client_rect(self):
        rect = win.client_rect(self.target)
        if not rect:
            return None
        # Win32 returns physical pixels; map relative to each monitor's origin.
        x, y, w, h = rect
        for screen in QApplication.screens():
            geo = screen.geometry()
            ratio = screen.devicePixelRatio()
            physical = QRect(
                geo.x(),
                geo.y(),
                round(geo.width() * ratio),
                round(geo.height() * ratio),
            )
            if physical.contains(x, y):
                return (
                    geo.x() + (x - geo.x()) / ratio,
                    geo.y() + (y - geo.y()) / ratio,
                    w / ratio,
                    h / ratio,
                )
        ratio = self.overlay.devicePixelRatioF()
        return x / ratio, y / ratio, w / ratio, h / ratio

    def capture_relative(self):
        if not self.target:
            return
        rect = self.logical_client_rect()
        if not rect:
            return
        x, y, w, h = rect
        r = self.overlay.geometry()
        if w > 0 and h > 0:
            self.relative = (
                (r.x() - x) / w,
                (r.y() - y) / h,
                r.width() / w,
                r.height() / h,
            )
            self.store.ui["relative"] = list(self.relative)

    def note_motion(self, rect):
        """Poll quickly while the host moves, slowly while it is still."""
        now = time.monotonic()
        if rect != self._last_client:
            self._last_client = rect
            self._active_until = now + 1.0
        interval = 33 if now < self._active_until else 100
        if interval != self.follow_timer.interval():
            self.follow_timer.setInterval(interval)

    def follow_target(self):
        if self.quitting:
            self.overlay.hide()
            return
        if self.picker is not None:
            self.overlay.hide()
            return
        visible = self.wanted_visible
        if self.target:
            if not win.user32.IsWindow(self.target):
                self.wanted_visible = False
                self.detach(manual=False)
                self.notice("Attached window closed · guides hidden")
                return
            rect = self.logical_client_rect()
            self.note_motion(rect)
            if not rect:
                visible = False
            else:
                if self.relative:
                    x, y, w, h = rect
                    rx, ry, rw, rh = self.relative
                    frame = QRect(
                        round(x + rx * w),
                        round(y + ry * h),
                        max(240, round(rw * w)),
                        max(180, round(rh * h)),
                    )
                    if frame != self.overlay.geometry():
                        self.overlay.setGeometry(frame)
                        self.sync_rect()
                # Keep guides out of other apps while attached; the host's own
                # palettes and dialogs count as the host. Controls stay usable.
                visible = visible and (
                    win.host_active(self.target) or win.own_foreground()
                )
        elif self.auto_pending and time.monotonic() >= self._next_auto:
            self._next_auto = time.monotonic() + 2.0
            self.try_auto_follow()
            return
        if visible != self.overlay.isVisible():
            self.overlay.setVisible(visible)
            if visible:
                win.set_click_through(int(self.overlay.winId()), self.state["locked"])

    # ------------------------------------------------------------ reference

    def load_reference(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a reference image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if filename:
            from PySide6.QtGui import QImageReader

            reader = QImageReader(filename)
            size = reader.size()
            if not reader.canRead() or size.width() * size.height() > 80_000_000:
                self.notice("Choose a readable image smaller than 80 megapixels.")
                return
            self.change("reference", filename)

    # -------------------------------------------------------------- presets

    def refresh_presets(self):
        selected = self.presets.currentText()
        self.presets.clear()
        self.presets.addItems(sorted(self.store.presets))
        if selected in self.store.presets:
            self.presets.setCurrentText(selected)

    def save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Save view preset", "Name this camera / view:"
        )
        name = name.strip()[:80]
        if not ok or not name:
            return
        if (
            name in self.store.presets
            and QMessageBox.question(self, "Replace preset?", f"Replace “{name}”?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.capture_state()
        self.store.presets[name] = copy.deepcopy(self.state)
        self.refresh_presets()
        self.presets.setCurrentText(name)
        self.save()

    def apply_preset(self, value):
        self.state.clear()
        self.state.update(validated(value))
        self.restore_reference()
        self.overlay.setGeometry(*self.state["rect"])
        self.restore_rect()
        self.overlay.set_locked(self.state["locked"])
        # Following continues: the preset's frame becomes the new relative frame.
        self.capture_relative()
        self.overlay.update()
        self.sync_ui()
        self.schedule_save()

    def cycle_preset(self, step):
        names = sorted(self.store.presets)
        if not names:
            self.overlay.flash("No presets saved")
            self.notice("No presets saved yet · use Save preset…")
            return
        current = self.presets.currentText()
        index = names.index(current) if current in names else (-1 if step > 0 else 0)
        name = names[(index + step) % len(names)]
        self.presets.setCurrentText(name)
        self.apply_preset(self.store.presets[name])
        label = f"{name}  ({names.index(name) + 1}/{len(names)})"
        self.overlay.flash(label)
        self.notice(f"Preset · {label}")

    def restore_reference(self):
        if self.state["reference"] and not Path(self.state["reference"]).is_file():
            self.state["reference"] = ""
            QTimer.singleShot(
                0,
                lambda: self.notice(
                    "Reference image is missing. Choose it again to restore it."
                ),
            )

    def load_preset(self):
        if self.presets.currentText() in self.store.presets:
            self.apply_preset(self.store.presets[self.presets.currentText()])

    def delete_preset(self):
        name = self.presets.currentText()
        if (
            name
            and QMessageBox.question(self, "Delete preset?", f"Delete “{name}”?")
            == QMessageBox.StandardButton.Yes
        ):
            self.store.presets.pop(name, None)
            self.refresh_presets()
            self.save()

    def export_preset(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export composition preset", "composition.json", "JSON (*.json)"
        )
        if not filename:
            return
        self.capture_state()
        value = copy.deepcopy(self.state)
        value["reference"] = ""
        try:
            Path(filename).write_text(
                json.dumps({"schema": 1, "state": value}, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            self.notice(f"Could not export preset: {exc}")

    def import_preset(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import composition preset", "", "JSON (*.json)"
        )
        if not filename:
            return
        try:
            path = Path(filename)
            if path.stat().st_size > 1_000_000:
                raise ValueError("File is too large")
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("schema") != 1
                or not isinstance(data.get("state"), dict)
            ):
                raise ValueError("Not an OverLayer preset")
            value = data["state"].copy()
            value["reference"] = ""
            self.apply_preset(value)
        except (OSError, ValueError, TypeError) as exc:
            self.notice(f"Could not import preset: {exc}")

    # ------------------------------------------------------------ shortcuts

    def hotkey_risk(self, spec):
        parsed = keys.parse(spec)
        if not parsed:
            return False
        mods, vk, _ = parsed
        both = mods & keys.MOD_CONTROL and mods & keys.MOD_ALT
        return bool(both and not mods & keys.MOD_WIN and win.altgr_conflict(vk))

    def refresh_hotkey_hints(self):
        """Update shortcut-dependent text; returns bindings that clash with AltGr."""
        hotkeys = self.store.hotkeys
        self.hint.setText(
            f"{hotkeys['hide_overlay']} hides guides · "
            f"{hotkeys['toggle_panel']} shows controls"
        )
        self.tray.setToolTip(f"OverLayer · {hotkeys['toggle_panel']} for controls")
        risky = []
        for name, warn in self.key_warns.items():
            risk = self.hotkey_risk(hotkeys[name])
            warn.setText(
                "⚠ This combination types a character on your keyboard layout "
                "(AltGr). Pick another."
                if risk
                else ""
            )
            warn.setVisible(risk)
            if risk:
                risky.append(hotkeys[name])
        return risky

    def sync_hotkey_edits(self):
        for name, edit in self.key_edits.items():
            edit.blockSignals(True)
            edit.setKeySequence(
                QKeySequence(
                    self.store.hotkeys[name], QKeySequence.SequenceFormat.PortableText
                )
            )
            edit.blockSignals(False)

    def apply_hotkeys(self):
        self.hotkeys.apply(self.store.hotkey_bindings())
        self.refresh_hotkey_hints()
        if self.hotkeys.failed:
            self.notice(
                "Shortcut unavailable: " + ", ".join(self.hotkeys.failed)
                + " (used by another app)."
            )

    def hotkey_recording(self, recording):
        # Registered shortcuts would fire instead of being typed into the box.
        self.recording_keys = recording
        if recording:
            self.hotkeys.close()
        else:
            self.apply_hotkeys()

    def hotkey_edited(self, name):
        seq = self.key_edits[name].keySequence()
        spec = keys.canonical(seq.toString(QKeySequence.SequenceFormat.PortableText))
        changed = False
        if not spec:
            self.notice("Use Ctrl, Alt, Shift or Win plus a letter, digit, F-key or arrow.")
        else:
            other = next(
                (
                    other
                    for other, existing in self.store.hotkeys.items()
                    if existing == spec and other != name
                ),
                None,
            )
            if other:
                self.notice(f"{spec} is already used for “{keys.LABELS[other]}”.")
            elif self.store.hotkeys[name] != spec:
                self.store.hotkeys[name] = spec
                changed = True
                self.schedule_save()
        self.sync_hotkey_edits()
        if changed and not self.recording_keys:
            self.apply_hotkeys()
        else:
            self.refresh_hotkey_hints()

    def restore_hotkeys(self):
        self.store.hotkeys.clear()
        self.store.hotkeys.update(keys.DEFAULT_HOTKEYS)
        self.sync_hotkey_edits()
        self.apply_hotkeys()
        self.schedule_save()
        self.notice("Default shortcuts restored")

    # --------------------------------------------------------------- saving

    def capture_state(self):
        r = self.overlay.geometry()
        self.state["rect"] = [r.x(), r.y(), r.width(), r.height()]
        panel = (
            self.normalGeometry()
            if self.isMaximized() or self.isMinimized()
            else self.geometry()
        )
        self.store.ui["panel_rect"] = [
            panel.x(),
            panel.y(),
            panel.width(),
            panel.height(),
        ]
        self.store.ui["panel_screen"] = self.screen().name()
        self.store.ui["overlay_screen"] = self.overlay.screen().name()
        self.store.ui["panel_maximized"] = self.isMaximized()

    def moveEvent(self, event):
        super().moveEvent(event)
        if getattr(self, "_geometry_ready", False) and not self.quitting:
            self.schedule_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_geometry_ready", False) and not self.quitting:
            self.schedule_save()

    def overlay_geometry_changed(self):
        if self._geometry_ready and not self.quitting:
            self.sync_rect()
            self.schedule_save()

    def schedule_save(self):
        self.save_timer.start(500)
        if hasattr(self, "saved_label"):
            self.saved_label.setText("Saving…")

    def save(self):
        self.capture_state()
        try:
            self.store.save()
            self.saved_label.setText(
                "All changes saved · " + time.strftime("%H:%M:%S")
            )
            return True
        except OSError as exc:
            logging.exception("Could not save settings")
            self.saved_label.setText("Could not save settings")
            self.notice(f"Could not save settings: {exc}")
            return False

    def reset_setup(self):
        self.capture_state()
        backup = copy.deepcopy(self.state)
        rect, locked = self.state["rect"][:], self.state["locked"]
        self.state.clear()
        self.state.update(copy.deepcopy(DEFAULTS))
        self.state.update(rect=rect, locked=locked)
        self.overlay.update()
        self.sync_ui()
        self.schedule_save()
        self.notice(
            "Reset · default guides and appearance; viewport kept", 8000, undo=True
        )
        # Set after notice(): clear_notice() drops the backup when it expires.
        self.reset_backup = backup

    def undo_reset(self):
        backup, self.reset_backup = self.reset_backup, None
        if backup is None:
            return
        # Keep the frame and lock state as they are now; restore the look.
        self.capture_state()
        backup["rect"] = self.state["rect"][:]
        backup["locked"] = self.state["locked"]
        self.state.clear()
        self.state.update(backup)
        self.overlay.update()
        self.sync_ui()
        self.schedule_save()
        self.notice("Reset undone · previous guides and appearance restored")

    def request_quit(self):
        self.show_panel()
        answer = QMessageBox.question(
            self,
            "Quit OverLayer?",
            "Remove the overlay and quit? Closing the control panel keeps it running.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.shutdown()
            QApplication.instance().quit()

    def shutdown(self):
        if self.quitting:
            return
        self.quitting = True
        self.wanted_visible = False
        self.save_timer.stop()
        self.notice_timer.stop()
        self.position_restore_timer.stop()
        self.save()
        self.hotkeys.close()
        self.follow_timer.stop()
        if self.picker is not None:
            self.picker.blockSignals(True)
            self.picker.close()
            self.picker = None
        self.tray.hide()
        self.overlay.hide()
        if self.taskbar_configured:
            try:
                taskbar.clear(int(self.winId()))
            except OSError:
                logging.exception("Could not clear Windows taskbar properties")
            self.taskbar_configured = False


def main():
    if os.name != "nt":
        raise SystemExit("OverLayer currently supports Windows 10/11 x64.")
    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [ctypes.c_wchar_p]
    set_app_id.restype = ctypes.c_long
    set_app_id("BogdanDemchenko.OverLayer")
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    app.setApplicationName("OverLayer")
    app.setOrganizationName("OverLayer")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    data_dir().mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=data_dir() / "overlayer.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    lock = QLockFile(str(data_dir() / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if not win.request_existing_controls():
            QMessageBox.information(
                None,
                "OverLayer is running",
                "OverLayer is starting or running. Press Ctrl+Alt+P for controls, or Ctrl+Alt+H to hide guides.",
            )
        return 0
    controller = Controller()
    controller.restore_reference()
    controller.show_panel()
    app.aboutToQuit.connect(controller.shutdown)
    result = app.exec()
    lock.unlock()
    return result
