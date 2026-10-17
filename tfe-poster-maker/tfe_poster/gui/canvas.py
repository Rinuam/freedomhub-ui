"""Editor canvas: background preview + WYSIWYG vector text items (scene units = source px)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPathStroker, QPen
from PySide6.QtWidgets import (QGraphicsBlurEffect, QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView)

from ..text.engine import layout
from ..text.render import qt_path
from .imageutil import to_pixmap

OCR_COL = QColor(255, 150, 40)
SEL_COL = QColor(40, 160, 255)
ERASE_COL = QColor(255, 60, 60)


def _qc(rgb, alpha=1.0) -> QColor:
    c = QColor(*rgb)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class TextItem(QGraphicsPathItem):
    """Fill path; stroke & shadow are child items so paint order matches the PDF."""

    def __init__(self, block, on_select, on_moved):
        super().__init__()
        self.block = block
        self._on_select, self._on_moved = on_select, on_moved
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.SizeAllCursor)
        self.shadow = QGraphicsPathItem(self)
        self.shadow.setFlag(QGraphicsItem.ItemStacksBehindParent)
        self.stroke = QGraphicsPathItem(self)
        self.stroke.setFlag(QGraphicsItem.ItemStacksBehindParent)
        self.sel = QGraphicsRectItem(self)
        pen = QPen(SEL_COL, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        self.sel.setPen(pen)
        self.rebuild()

    def rebuild(self) -> None:
        b = self.block
        self.setPos(0, 0)
        if not b.text.strip():
            self.setPath(qt_path(layout(type(b)(0, "·", cx=b.cx, cy=b.cy, size=b.size))))
            return
        laid = layout(b)
        path = qt_path(laid)
        self.setPath(path)
        self.setBrush(QBrush(_qc(b.fill, b.fill_opacity)))
        if b.synth_bold > 0:
            pen = QPen(_qc(b.fill, b.fill_opacity), b.size * 0.03 * b.synth_bold)
            pen.setJoinStyle(Qt.RoundJoin)
            self.setPen(pen)
        else:
            self.setPen(Qt.NoPen)
        if b.stroke_on and b.stroke_width > 0:
            st = QPainterPathStroker()
            st.setWidth(b.size * b.stroke_width / 100 * 2)
            st.setJoinStyle(Qt.RoundJoin)
            st.setCapStyle(Qt.RoundCap)
            self.stroke.setPath(st.createStroke(path).united(path))
            self.stroke.setBrush(QBrush(_qc(b.stroke, b.stroke_opacity)))
            self.stroke.setPen(Qt.NoPen)
            self.stroke.show()
        else:
            self.stroke.hide()
        if b.shadow_on:
            sp = self.stroke.path() if self.stroke.isVisible() else path
            self.shadow.setPath(sp.translated(b.size * b.shadow_dx / 100, b.size * b.shadow_dy / 100))
            self.shadow.setBrush(QBrush(_qc(b.shadow, b.shadow_opacity)))
            self.shadow.setPen(Qt.NoPen)
            if b.shadow_blur > 0:
                eff = QGraphicsBlurEffect()
                eff.setBlurRadius(b.size * b.shadow_blur / 100 * 2.2)
                eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
                self.shadow.setGraphicsEffect(eff)
            else:
                self.shadow.setGraphicsEffect(None)
            self.shadow.show()
        else:
            self.shadow.hide()
        r = path.boundingRect().adjusted(-4, -4, 4, 4)
        self.sel.setRect(r)
        self.sel.setVisible(self.isSelected())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.sel.setVisible(bool(value))
            if value:
                self._on_select(self.block.id)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        p = self.pos()
        if abs(p.x()) > 0.01 or abs(p.y()) > 0.01:
            self.block.cx += p.x()
            self.block.cy += p.y()
            self.block.auto_fit = False
            self.rebuild()
            self._on_moved(self.block.id)


class OcrBoxItem(QGraphicsRectItem):
    """Raster (non-vectorised) text line: click to select."""

    def __init__(self, block, on_select):
        x, y, w, h = block.box
        super().__init__(QRectF(x, y, w, h))
        self.block = block
        self._on_select = on_select
        pen = QPen(OCR_COL, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        c = QColor(OCR_COL)
        c.setAlpha(30)
        self.setBrush(c)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        self._on_select(self.block.id)
        super().mousePressEvent(ev)


class EraseItem(QGraphicsRectItem):
    def __init__(self, region):
        super().__init__(QRectF(region.x, region.y, region.w, region.h))
        self.region = region
        pen = QPen(ERASE_COL, 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        c = QColor(ERASE_COL)
        c.setAlpha(60)
        self.setBrush(c)
        self.setFlag(QGraphicsItem.ItemIsSelectable)


class Canvas(QGraphicsView):
    blockSelected = Signal(int)
    blockMoved = Signal(int)
    addTextAt = Signal(float, float)
    eraseRect = Signal(float, float, float, float)
    eraseDeleted = Signal(object)
    viewChanged = Signal()

    def __init__(self, parent=None):
        self.scene_ = QGraphicsScene()
        super().__init__(self.scene_, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(52, 52, 56))
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.bg = QGraphicsPixmapItem()
        self.bg.setTransformationMode(Qt.SmoothTransformation)
        self.bg.setZValue(-10)
        self.scene_.addItem(self.bg)
        self.tool = "select"            # select | text | erase
        self.text_items: dict[int, TextItem] = {}
        self.ocr_items: dict[int, OcrBoxItem] = {}
        self.erase_items: list[EraseItem] = []
        self._rubber = None
        self._origin = None
        self._panning = None
        self.show_erase = True
        self.project = None

    # ------------------------------------------------------------- content
    def set_background(self, img, px_per_src: float) -> None:
        self.bg.setPixmap(to_pixmap(img))
        self.bg.setScale(1.0 / px_per_src)

    def set_project(self, project) -> None:
        self.project = project
        w, h = project.size
        self.scene_.setSceneRect(-w * 0.1, -h * 0.1, w * 1.2, h * 1.2)
        self.rebuild_items()
        self.fit()

    def rebuild_items(self) -> None:
        for it in list(self.text_items.values()) + list(self.ocr_items.values()) + self.erase_items:
            self.scene_.removeItem(it)
        self.text_items, self.ocr_items, self.erase_items = {}, {}, []
        p = self.project
        if not p:
            return
        for b in p.blocks:
            self._add_block_item(b)
        for r in p.erase_regions:
            it = EraseItem(r)
            it.setVisible(self.show_erase)
            self.scene_.addItem(it)
            self.erase_items.append(it)

    def _add_block_item(self, b) -> None:
        if b.vectorise:
            it = TextItem(b, self.blockSelected.emit, self.blockMoved.emit)
            it.setZValue(10)
            self.scene_.addItem(it)
            self.text_items[b.id] = it
        elif not b.user_added:
            it = OcrBoxItem(b, self.blockSelected.emit)
            it.setZValue(5)
            self.scene_.addItem(it)
            self.ocr_items[b.id] = it

    def refresh_block(self, b) -> None:
        for d in (self.text_items, self.ocr_items):
            it = d.pop(b.id, None)
            if it is not None:
                was = it.isSelected()
                self.scene_.removeItem(it)
        if b in self.project.blocks:
            self._add_block_item(b)
            self.select_block(b.id, emit=False)

    def select_block(self, bid: int, emit: bool = True) -> None:
        self.scene_.blockSignals(True)
        for it in self.scene_.selectedItems():
            it.setSelected(False)
        it = self.text_items.get(bid) or self.ocr_items.get(bid)
        if it is not None:
            it.setSelected(True)
            if isinstance(it, TextItem):
                it.sel.setVisible(True)
            self.ensureVisible(it.sceneBoundingRect(), 60, 60)
        self.scene_.blockSignals(False)
        for t in self.text_items.values():
            t.sel.setVisible(t.isSelected())

    def set_text_visible(self, on: bool) -> None:
        for it in self.text_items.values():
            it.setVisible(on)
        for it in self.ocr_items.values():
            it.setVisible(on)

    def set_erase_visible(self, on: bool) -> None:
        self.show_erase = on
        for it in self.erase_items:
            it.setVisible(on)

    def fit(self) -> None:
        if self.project:
            w, h = self.project.size
            self.fitInView(QRectF(0, 0, w, h), Qt.KeepAspectRatio)

    def visible_source_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    # --------------------------------------------------------------- input
    def wheelEvent(self, ev):
        f = 1.0015 ** ev.angleDelta().y()
        self.scale(f, f)
        self.viewChanged.emit()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton or (ev.button() == Qt.LeftButton and ev.modifiers() & Qt.AltModifier):
            self._panning = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        sp = self.mapToScene(ev.position().toPoint())
        if self.tool == "text" and ev.button() == Qt.LeftButton:
            self.addTextAt.emit(sp.x(), sp.y())
            return
        if self.tool == "erase" and ev.button() == Qt.LeftButton:
            self._origin = sp
            self._rubber = QGraphicsRectItem(QRectF(sp, sp))
            pen = QPen(ERASE_COL, 1.5)
            pen.setCosmetic(True)
            self._rubber.setPen(pen)
            c = QColor(ERASE_COL)
            c.setAlpha(60)
            self._rubber.setBrush(c)
            self.scene_.addItem(self._rubber)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._panning is not None:
            d = ev.position() - self._panning
            self._panning = ev.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self._rubber is not None:
            sp = self.mapToScene(ev.position().toPoint())
            self._rubber.setRect(QRectF(self._origin, sp).normalized())
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._panning is not None:
            self._panning = None
            self.setCursor(Qt.ArrowCursor)
            self.viewChanged.emit()
            return
        if self._rubber is not None:
            r = self._rubber.rect()
            self.scene_.removeItem(self._rubber)
            self._rubber = None
            if r.width() > 2 and r.height() > 2:
                self.eraseRect.emit(r.x(), r.y(), r.width(), r.height())
            return
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        sel = self.scene_.selectedItems()
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for it in sel:
                if isinstance(it, EraseItem):
                    self.eraseDeleted.emit(it.region)
            return
        step = 10 if ev.modifiers() & Qt.ShiftModifier else 1
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if ev.key() in d:
            for it in sel:
                if isinstance(it, TextItem):
                    it.block.cx += d[ev.key()][0]
                    it.block.cy += d[ev.key()][1]
                    it.block.auto_fit = False
                    it.rebuild()
                    self.blockMoved.emit(it.block.id)
            return
        super().keyPressEvent(ev)
