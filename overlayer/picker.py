"""Per-monitor viewport selection with stable coordinates and mouse capture."""

from PySide6.QtCore import Qt, QPoint, QRect, Signal, QObject
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


def selection_rect(start, current):
    if start is None:
        return QRect()
    return QRect(
        min(start.x(), current.x()),
        min(start.y(), current.y()),
        abs(current.x() - start.x()),
        abs(current.y() - start.y()),
    )


class SelectionSurface(QWidget):
    def __init__(self, screen, picker):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.picker = picker
        self.start = None
        self.setWindowTitle("OverLayer · draw viewport area")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.winId()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self.current = self.mapFromGlobal(QCursor.pos())

    def selection(self):
        return selection_rect(self.start, self.current)

    def bounded_point(self, point):
        return QPoint(
            max(0, min(self.width(), point.x())), max(0, min(self.height(), point.y()))
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Fully transparent pixels in a layered Windows window can pass clicks
        # through. Keep the selected area hit-testable while visually clear.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        shade = QPainterPath()
        shade.addRect(self.rect())
        selection = self.selection()
        if not selection.isNull():
            hole = QPainterPath()
            hole.addRect(selection)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(6, 13, 22, 125))
        p.setPen(QPen(QColor("#e9bd78"), 1.5))
        if self.start is not None:
            p.drawRect(selection)
            label = f"{selection.width()} × {selection.height()} px · release to fit"
        else:
            label = "Click and drag over your viewport · Esc to cancel"
            p.drawLine(self.current.x(), 0, self.current.x(), self.height())
            p.drawLine(0, self.current.y(), self.width(), self.current.y())
        x = max(12, min(self.current.x() + 18, self.width() - 372))
        y = max(12, min(self.current.y() + 22, self.height() - 42))
        box = QRect(x, y, 360, 30)
        p.fillRect(box, QColor("#111923"))
        p.setPen(QColor("#e7edf2"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.picker.finish(None)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.picker.active = self
            self.start = self.bounded_point(event.position().toPoint())
            self.current = QPoint(self.start)
            self.grabMouse()
            self.update()

    def mouseMoveEvent(self, event):
        self.current = self.bounded_point(event.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.current = self.bounded_point(event.position().toPoint())
            self.releaseMouse()
            rect = self.selection()
            rect.moveTopLeft(self.mapToGlobal(rect.topLeft()))
            self.picker.finish(rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.picker.finish(None)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self.picker.done:
            self.picker.finish(None)
        event.accept()


class AreaPicker(QObject):
    finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.done = False
        self.active = None
        # One HWND per QScreen: each keeps its own DPI conversion. A single
        # virtual-desktop window cannot represent mixed-scale monitors correctly.
        self.surfaces = [
            SelectionSurface(screen, self) for screen in QApplication.screens()
        ]

    def focus_surface(self):
        if self.active is not None:
            return self.active
        screen = QApplication.screenAt(QCursor.pos())
        return next(
            (surface for surface in self.surfaces if surface.screen() == screen),
            self.surfaces[0],
        )

    def show(self):
        for surface in self.surfaces:
            surface.show()
        self.activateWindow()

    def raise_(self):
        if not self.done:
            self.focus_surface().raise_()

    def activateWindow(self):
        if not self.done:
            surface = self.focus_surface()
            surface.raise_()
            surface.activateWindow()
            surface.setFocus()

    def setFocus(self):
        if not self.done:
            self.focus_surface().setFocus()

    def close(self):
        self.finish(None)

    def finish(self, result):
        if self.done:
            return
        self.done = True
        for surface in self.surfaces:
            if QWidget.mouseGrabber() is surface:
                surface.releaseMouse()
            surface.hide()
            surface.close()
            surface.deleteLater()
        self.finished.emit(result)
        self.deleteLater()
