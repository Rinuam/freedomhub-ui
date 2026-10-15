"""Before/after split view with zoom (wheel), pan (drag) and a draggable divider."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import QWidget

from .imageutil import Pyramid, to_qimage


class CompareView(QWidget):
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(300, 300)
        self.before: Pyramid | None = None
        self.after: Pyramid | None = None
        self.labels = ("Before", "After")
        self.split = 0.5
        self.zoom = 0.1
        self.cx = self.cy = 0.0
        self._drag = None
        self._dpi = 300

    # ----------------------------------------------------------------- data
    def set_images(self, before: np.ndarray, after: np.ndarray,
                   labels=("Before", "After"), dpi: int = 300) -> None:
        keep = self.before is not None and self.before.w == before.shape[1] \
            and self.before.h == before.shape[0]
        self.before, self.after = Pyramid(before), Pyramid(after)
        self.labels, self._dpi = labels, dpi
        if not keep:
            self.fit()
        self.update()

    def clear(self) -> None:
        self.before = self.after = None
        self.update()

    def fit(self) -> None:
        if not self.before:
            return
        self.zoom = min(self.width() / self.before.w, self.height() / self.before.h) * 0.98
        self.cx, self.cy = self.before.w / 2, self.before.h / 2
        self.zoomChanged.emit(self.zoom)
        self.update()

    def actual(self) -> None:
        self.set_zoom(1.0)

    def set_zoom(self, z: float, anchor: QPointF | None = None) -> None:
        if not self.before:
            return
        z = float(np.clip(z, 0.01, 8.0))
        if anchor is not None:
            ix, iy = self._to_img(anchor)
            self.zoom = z
            self.cx = ix - (anchor.x() - self.width() / 2) / z
            self.cy = iy - (anchor.y() - self.height() / 2) / z
        else:
            self.zoom = z
        self.zoomChanged.emit(self.zoom)
        self.update()

    def _to_img(self, p: QPointF):
        return (self.cx + (p.x() - self.width() / 2) / self.zoom,
                self.cy + (p.y() - self.height() / 2) / self.zoom)

    # ---------------------------------------------------------------- paint
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(60, 60, 64))
        if not self.before:
            p.setPen(QColor(200, 200, 200))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Render a preview or export to compare before / after")
            return
        w, h = self.width(), self.height()
        x0 = self.cx - w / 2 / self.zoom
        y0 = self.cy - h / 2 / self.zoom
        x1, y1 = x0 + w / self.zoom, y0 + h / self.zoom
        sx = int(round(w * self.split))
        if sx > 0:
            img = self.before.render(x0, y0, x0 + sx / self.zoom, y1, sx, h)
            p.drawImage(0, 0, to_qimage(img))
        if sx < w:
            img = self.after.render(x0 + sx / self.zoom, y0, x1, y1, w - sx, h)
            p.drawImage(sx, 0, to_qimage(img))
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(sx, 0, sx, h)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(sx, h / 2), 9, 9)
        f = QFont()
        f.setBold(True)
        p.setFont(f)
        for text, x, align in ((self.labels[0], 10, Qt.AlignLeft), (self.labels[1], w - 10, Qt.AlignRight)):
            r = p.fontMetrics().boundingRect(text)
            bx = x if align == Qt.AlignLeft else x - r.width() - 12
            p.fillRect(bx, 8, r.width() + 12, r.height() + 6, QColor(0, 0, 0, 150))
            p.setPen(QColor(255, 255, 255))
            p.drawText(bx + 6, 8 + r.height(), text)
        info = f"zoom {self.zoom * 100:.0f}%  (100% = 1 output pixel at {self._dpi} dpi)"
        p.fillRect(8, h - 28, p.fontMetrics().horizontalAdvance(info) + 12, 22, QColor(0, 0, 0, 150))
        p.drawText(14, h - 12, info)

    # ---------------------------------------------------------------- input
    def wheelEvent(self, ev) -> None:
        f = 1.0015 ** ev.angleDelta().y()
        self.set_zoom(self.zoom * f, ev.position())

    def mousePressEvent(self, ev) -> None:
        sx = self.width() * self.split
        if abs(ev.position().x() - sx) < 14:
            self._drag = ("split", None)
        else:
            self._drag = ("pan", (ev.position(), self.cx, self.cy))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev) -> None:
        if not self._drag:
            near = abs(ev.position().x() - self.width() * self.split) < 14
            self.setCursor(Qt.SplitHCursor if near else Qt.OpenHandCursor)
            return
        kind, data = self._drag
        if kind == "split":
            self.split = float(np.clip(ev.position().x() / max(1, self.width()), 0, 1))
        else:
            start, cx, cy = data
            d = ev.position() - start
            self.cx, self.cy = cx - d.x() / self.zoom, cy - d.y() / self.zoom
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, ev) -> None:
        if self.zoom < 0.9:
            self.set_zoom(1.0, ev.position())
        else:
            self.fit()

    def resizeEvent(self, ev) -> None:
        if self.before and ev.oldSize().width() <= 0:
            self.fit()
