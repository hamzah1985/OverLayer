from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from .geometry import (
    anchors,
    aspect_value,
    composed_paths,
    frame_rect,
    ratio_label,
    transform,
)
from .windows import set_click_through

MIN_WIDTH, MIN_HEIGHT = 240, 180
ARROWS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}


class Overlay(QWidget):
    edited = Signal()
    placement_changed = Signal()
    reference_error = Signal(str)

    def __init__(self, state):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._report_geometry = False
        self.setWindowTitle("OverLayer · composition overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.state = state
        self.drag = None
        self.anchor_origin = None
        self.hud = ""
        self.hud_timer = QTimer(self)
        self.hud_timer.setSingleShot(True)
        self.hud_timer.timeout.connect(self.clear_hud)
        self.reference = QImage()
        self.reference_path = None
        self.setGeometry(*state["rect"])
        self.set_locked(state["locked"])
        self._report_geometry = True

    def moveEvent(self, event):
        super().moveEvent(event)
        if getattr(self, "_report_geometry", False):
            self.placement_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_report_geometry", False):
            self.placement_changed.emit()

    def set_locked(self, locked):
        self.state["locked"] = locked
        # Native styles avoid recreating the HWND during a lock toggle.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        set_click_through(int(self.winId()), locked)
        self.update()

    def closeEvent(self, event):
        # This surface has no independent exit. Controls/tray own its lifecycle.
        event.ignore()

    def flash(self, text, ms=1400):
        """Show a short label on the frame, even while locked."""
        self.hud = text
        self.hud_timer.start(ms)
        self.update()

    def clear_hud(self):
        self.hud = ""
        self.update()

    def guide_rect(self):
        return QRectF(
            *frame_rect(self.width(), self.height(), aspect_value(self.state))
        )

    def point_position(self, p):
        x, y = transform(p, self.state)
        rect = self.guide_rect()
        return QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())

    def pens(self, color, width, dashed=False):
        """Halo pen (when enabled) under the guide pen, so lines read on any image."""
        pens = []
        if self.state["halo"]:
            halo = QColor(255, 255, 255) if color.lightness() < 128 else QColor(0, 0, 0)
            halo.setAlphaF(min(1.0, color.alphaF() * 0.55))
            pens.append(QPen(halo, width + 2))
        pens.append(QPen(color, width))
        if dashed:
            for pen in pens:
                # Dash lengths scale with pen width; keep both strokes in step.
                scale = width / pen.widthF()
                pen.setDashPattern([4 * scale, 3 * scale])
        return pens

    def load_reference(self):
        if self.reference_path == self.state["reference"]:
            return
        self.reference_path = self.state["reference"]
        self.reference = QImage(self.reference_path) if self.reference_path else QImage()
        if self.reference_path and self.reference.isNull():
            name = self.reference_path.replace("\\", "/").rsplit("/", 1)[-1]
            QTimer.singleShot(0, lambda: self.reference_error.emit(name))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = self.guide_rect()
        locked = self.state["locked"]
        if not locked:
            p.fillRect(self.rect(), QColor(9, 16, 22, 55))
        if self.state["dim_outside"] and frame.size() != QRectF(self.rect()).size():
            outside = QPainterPath()
            outside.addRect(QRectF(self.rect()))
            inside = QPainterPath()
            inside.addRect(frame)
            p.fillPath(outside.subtracted(inside), QColor(0, 0, 0, 120))
        self.load_reference()
        if not self.reference.isNull():
            p.save()
            p.setClipRect(frame)
            # Fit without distortion, then apply the user's scale and offset.
            target_size = self.reference.size().scaled(
                frame.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio
            )
            factor = self.state["reference_scale"] / 100
            target = QRectF(
                0, 0, target_size.width() * factor, target_size.height() * factor
            )
            target.moveCenter(
                frame.center()
                + QPointF(
                    frame.width() * self.state["reference_dx"] / 100,
                    frame.height() * self.state["reference_dy"] / 100,
                )
            )
            p.setOpacity(self.state["reference_opacity"] / 100)
            p.drawImage(target, self.reference)
            p.restore()
        color = QColor(self.state["color"])
        color.setAlphaF(self.state["opacity"] / 100)
        thickness = self.state["thickness"]
        p.save()
        p.setClipRect(frame.adjusted(-1, -1, 1, 1))
        guides = QPainterPath()
        for points in composed_paths(frame.width(), frame.height(), self.state):
            for i, (x, y) in enumerate(points):
                pt = QPointF(
                    frame.x() + x * frame.width(), frame.y() + y * frame.height()
                )
                guides.moveTo(pt) if i == 0 else guides.lineTo(pt)
        for pen in self.pens(color, thickness):
            p.setPen(pen)
            p.drawPath(guides)
        if self.state["margins"]:
            inset = self.state["margin_pct"] / 100
            safe = frame.adjusted(
                frame.width() * inset,
                frame.height() * inset,
                -frame.width() * inset,
                -frame.height() * inset,
            )
            for pen in self.pens(color, thickness, dashed=True):
                p.setPen(pen)
                p.drawRect(safe)
        if self.state["focal"]:
            center = self.point_position(self.state["focus"])
            for pen in self.pens(color, thickness):
                p.setPen(pen)
                p.drawEllipse(center, 10, 10)
                p.drawLine(center + QPointF(-17, 0), center + QPointF(17, 0))
                p.drawLine(center + QPointF(0, -17), center + QPointF(0, 17))
        p.restore()
        if self.state["border"] or not locked:
            edge = frame.adjusted(1, 1, -1, -1)
            for pen in self.pens(color, 1, dashed=not locked):
                p.setPen(pen)
                p.drawRect(edge)
        if not locked:
            p.setPen(QPen(QColor("#99d9d2"), 1.5))
            p.setBrush(QColor("#122f34"))
            for point in anchors(self.state).values():
                pos = self.point_position(point)
                p.drawEllipse(pos, 7, 7)
            p.setPen(QPen(QColor("#99d9d2"), 2))
            p.setBrush(QColor("#122f34"))
            # Eight clearly visible handles: corners and edge midpoints.
            for x, y in (
                (7, 7),
                (self.width() / 2, 7),
                (self.width() - 7, 7),
                (7, self.height() / 2),
                (self.width() - 7, self.height() / 2),
                (7, self.height() - 7),
                (self.width() / 2, self.height() - 7),
                (self.width() - 7, self.height() - 7),
            ):
                p.drawEllipse(QPointF(x, y), 5, 5)
        if self.hud:
            self.paint_hud(p)
        p.end()

    def paint_hud(self, p):
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(self.hud) + 24
        box = QRectF(0, 26, min(width, self.width() - 20), 28)
        box.moveLeft((self.width() - box.width()) / 2)
        p.setPen(QPen(QColor("#35485a"), 1))
        p.setBrush(QColor(17, 25, 35, 235))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("#e7edf2"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.hud)

    def size_text(self):
        ratio = ratio_label(self.width(), self.height())
        return f"{self.width()} × {self.height()}  ·  {ratio}"

    def hit_test(self, pos):
        for key, point in anchors(self.state).items():
            if (self.point_position(point) - pos).manhattanLength() < 21:
                return ("anchor", key)
        edges = ""
        if pos.x() < 18:
            edges += "l"
        elif pos.x() > self.width() - 18:
            edges += "r"
        if pos.y() < 18:
            edges += "t"
        elif pos.y() > self.height() - 18:
            edges += "b"
        return ("resize", edges) if edges else ("move", "")

    def mousePressEvent(self, event):
        if self.state["locked"] or event.button() != Qt.MouseButton.LeftButton:
            return
        self.drag = (
            self.hit_test(event.position()),
            event.globalPosition(),
            QRect(self.geometry()),
        )
        self.hud_timer.stop()
        kind, key = self.drag[0]
        if kind == "anchor":
            # Keep the grab offset so the point does not jump under the cursor.
            self.anchor_origin = (
                event.position(),
                self.point_position(self.state[key]),
            )

    def mouseMoveEvent(self, event):
        if self.state["locked"]:
            return
        if not self.drag:
            kind, edges = self.hit_test(event.position())
            cursor = Qt.CursorShape.SizeAllCursor
            if kind == "anchor":
                cursor = Qt.CursorShape.CrossCursor
            elif kind == "resize":
                cursor = (
                    Qt.CursorShape.SizeFDiagCursor
                    if edges in ("lt", "rb")
                    else Qt.CursorShape.SizeBDiagCursor
                    if edges in ("rt", "lb")
                    else Qt.CursorShape.SizeHorCursor
                    if edges in ("l", "r")
                    else Qt.CursorShape.SizeVerCursor
                )
            self.setCursor(cursor)
            return
        (kind, key), start, original_rect = self.drag
        # Never mutate the stored starting rectangle. Each event's delta is
        # measured from mouse-down, not from the previous mouse-move event.
        rect = QRect(original_rect)
        delta = (event.globalPosition() - start).toPoint()
        precise = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if precise:
            delta = (event.globalPosition() - start).toPoint() / 5
        if kind == "anchor":
            frame = self.guide_rect()
            press, origin = self.anchor_origin or (event.position(), event.position())
            move = event.position() - press
            if precise:
                move = move / 5
            at = origin + move
            x = max(0, min(1, (at.x() - frame.x()) / frame.width()))
            y = max(0, min(1, (at.y() - frame.y()) / frame.height()))
            self.state[key] = list(transform((x, y), self.state, inverse=True))
            if key in ("left_vp", "right_vp"):
                other = "right_vp" if key == "left_vp" else "left_vp"
                self.state[other][1] = self.state[key][1]
            self.hud = f"{x * 100:.0f}%  ·  {y * 100:.0f}%"
            self.update()
        elif kind == "move":
            self.move(rect.topLeft() + delta)
        else:
            if "l" in key:
                rect.setLeft(min(rect.right() - (MIN_WIDTH - 1), rect.left() + delta.x()))
            if "r" in key:
                rect.setRight(max(rect.left() + (MIN_WIDTH - 1), rect.right() + delta.x()))
            if "t" in key:
                rect.setTop(min(rect.bottom() - (MIN_HEIGHT - 1), rect.top() + delta.y()))
            if "b" in key:
                rect.setBottom(max(rect.top() + (MIN_HEIGHT - 1), rect.bottom() + delta.y()))
            self.setGeometry(rect)
        if kind != "anchor":
            self.hud = self.size_text()
            self.update()
        self.edited.emit()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.anchor_origin = None
        if self.hud:
            self.hud_timer.start(900)
        self.edited.emit()

    def keyPressEvent(self, event):
        step = ARROWS.get(event.key())
        if step is None or self.state["locked"]:
            super().keyPressEvent(event)
            return
        amount = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        dx, dy = step[0] * amount, step[1] * amount
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.resize(
                max(MIN_WIDTH, self.width() + dx), max(MIN_HEIGHT, self.height() + dy)
            )
            self.flash(self.size_text(), 900)
        else:
            self.move(self.x() + dx, self.y() + dy)
            self.flash(f"{self.x()}, {self.y()}", 900)
        event.accept()
        self.edited.emit()
