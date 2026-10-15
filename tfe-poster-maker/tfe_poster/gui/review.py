"""Review screen: canvas with text boxes + per-box editor (text, font, size, vectorise)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QRectF, Signal, QSignalBlocker
from PySide6.QtGui import QBrush, QColor, QPen, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QCompleter, QDoubleSpinBox, QFormLayout, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSlider, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..fonts import default_font_id, fitz_font, list_fonts
from .imageutil import downscale, to_pixmap

ON = QColor(40, 200, 120)
OFF = QColor(255, 150, 40)
PREVIEW_SIDE = 2400


class CanvasView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(60, 60, 64))

    def wheelEvent(self, ev):
        f = 1.0015 ** ev.angleDelta().y()
        self.scale(f, f)

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


class BoxItem(QGraphicsRectItem):
    def __init__(self, idx: int, rect: QRectF, on_click):
        super().__init__(rect)
        self.idx = idx
        self._on_click = on_click
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        self._on_click(self.idx)
        ev.accept()


class ReviewPanel(QWidget):
    changed = Signal()            # any edit that invalidates a rendered preview
    renderRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self._items: list[BoxItem] = []
        self._labels: list[QGraphicsSimpleTextItem] = []
        self._k = 1.0                 # canvas px -> preview px
        self._showing_result = False
        self._result_preview = None

        self.scene = QGraphicsScene(self)
        self.view = CanvasView(self.scene)
        self._pix = None

        # ---- table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Vector", "Text", "Conf.", "Size pt"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._table_item_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        btn_all = QPushButton("Vectorise all")
        btn_none = QPushButton("None")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        self.show_result = QCheckBox("Show rendered result")
        self.show_result.toggled.connect(self._toggle_result)
        btn_fit = QPushButton("Fit")
        btn_fit.clicked.connect(self.view.fit)
        self.btn_render = QPushButton("Render preview")
        self.btn_render.clicked.connect(self.renderRequested.emit)

        # ---- editor
        self.ed_text = QLineEdit()
        self.ed_text.textEdited.connect(self._edit_text)
        self.ed_font = QComboBox()
        self.ed_font.setEditable(True)
        self.ed_font.setInsertPolicy(QComboBox.NoInsert)
        self.ed_font.setMaxVisibleItems(25)
        comp = self.ed_font.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.ed_font.activated.connect(self._edit_font)
        self.ed_auto = QCheckBox("Auto-fit")
        self.ed_auto.toggled.connect(self._edit_size)
        self.ed_size = QDoubleSpinBox()
        self.ed_size.setRange(2, 2000)
        self.ed_size.setDecimals(1)
        self.ed_size.setSuffix(" pt")
        self.ed_size.valueChanged.connect(self._edit_size)
        self.ed_colour = QPushButton()
        self.ed_colour.clicked.connect(self._edit_colour)
        self.ed_align = QComboBox()
        self.ed_align.addItems(["center", "left", "right"])
        self.ed_align.currentTextChanged.connect(self._edit_align)
        self.ed_grow = QSlider(Qt.Horizontal)
        self.ed_grow.setRange(0, 40)       # 0..4.0
        self.ed_grow.valueChanged.connect(self._edit_grow)
        self.ed_vec = QCheckBox("Vectorise this box (inpaint raster text, place vector text)")
        self.ed_vec.toggled.connect(self._edit_vec)
        self.btn_font_all = QPushButton("Use this font for all vectorised boxes")
        self.btn_font_all.clicked.connect(self._font_to_all)
        self.ed_info = QLabel()
        self.ed_info.setWordWrap(True)

        size_row = QHBoxLayout()
        size_row.addWidget(self.ed_size, 1)
        size_row.addWidget(self.ed_auto)
        form = QFormLayout()
        form.addRow(self.ed_vec)
        form.addRow("Text", self.ed_text)
        form.addRow("Font", self.ed_font)
        form.addRow("", self.btn_font_all)
        form.addRow("Size", size_row)
        form.addRow("Colour", self.ed_colour)
        form.addRow("Anchor", self.ed_align)
        form.addRow("Inpaint grow", self.ed_grow)
        form.addRow(self.ed_info)
        self.editor = QGroupBox("Selected box")
        self.editor.setLayout(form)
        self.editor.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(btn_all)
        top.addWidget(btn_none)
        top.addStretch(1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(top)
        rl.addWidget(self.table, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.editor)
        scroll.setMinimumHeight(260)
        rl.addWidget(scroll)

        vbar = QHBoxLayout()
        vbar.addWidget(btn_fit)
        vbar.addWidget(self.show_result)
        vbar.addStretch(1)
        vbar.addWidget(self.btn_render)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.view, 1)
        ll.addLayout(vbar)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)
        self._fonts_loaded = False

    # ------------------------------------------------------------------ data
    def _ensure_fonts(self):
        if self._fonts_loaded:
            return
        with QSignalBlocker(self.ed_font):
            for f in list_fonts():
                self.ed_font.addItem(f.label, f.id)
        self._fonts_loaded = True

    def set_project(self, project) -> None:
        self._ensure_fonts()
        self.project = project
        self._result_preview = None
        with QSignalBlocker(self.show_result):
            self.show_result.setChecked(False)
        self.show_result.setEnabled(False)
        self.refresh_background()
        self._rebuild()
        self.view.fit()

    def refresh_background(self) -> None:
        p = self.project
        if p is None:
            return
        if self._showing_result and self._result_preview is not None:
            img = self._result_preview
        elif p.canvas is not None:
            img, _ = downscale(p.canvas, PREVIEW_SIDE)
        else:   # before upscaling finishes: place the source on the sheet
            import cv2
            from ..layout import compose_canvas
            lay = p.layout
            k = PREVIEW_SIDE / max(lay.canvas_w, lay.canvas_h)
            small = cv2.resize(p.src, (max(1, int(lay.place_w * k)), max(1, int(lay.place_h * k))),
                               interpolation=cv2.INTER_AREA)
            img = np.empty((int(lay.canvas_h * k), int(lay.canvas_w * k), 3), np.uint8)
            img[:] = p.edge_colour
            x, y = int(lay.place_x * k), int(lay.place_y * k)
            img[y:y + small.shape[0], x:x + small.shape[1]] = small[:img.shape[0] - y, :img.shape[1] - x]
        self._k = img.shape[1] / p.layout.canvas_w
        if self._pix is None:
            self._pix = self.scene.addPixmap(to_pixmap(img))
            self._pix.setZValue(-1)
            self._pix.setTransformationMode(Qt.SmoothTransformation)
        else:
            self._pix.setPixmap(to_pixmap(img))
        self.scene.setSceneRect(0, 0, img.shape[1], img.shape[0])
        self._place_items()

    def set_result_preview(self, flat: np.ndarray) -> None:
        self._result_preview, _ = downscale(flat, PREVIEW_SIDE)
        self.show_result.setEnabled(True)
        if self.show_result.isChecked():
            self.refresh_background()

    def _toggle_result(self, on: bool) -> None:
        self._showing_result = on
        self.refresh_background()

    def _box_rect(self, b) -> QRectF:
        lay = self.project.layout
        x0, y0 = lay.src_to_canvas(b.x, b.y)
        x1, y1 = lay.src_to_canvas(b.x + b.w, b.y + b.h)
        k = self._k
        return QRectF(x0 * k, y0 * k, (x1 - x0) * k, (y1 - y0) * k)

    def _rebuild(self) -> None:
        for it in self._items + self._labels:
            self.scene.removeItem(it)
        self._items, self._labels = [], []
        p = self.project
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(p.boxes))
            for i, b in enumerate(p.boxes):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk.setCheckState(Qt.Checked if b.vectorise else Qt.Unchecked)
                self.table.setItem(i, 0, chk)
                self.table.setItem(i, 1, QTableWidgetItem(b.text))
                for c, v in ((2, f"{b.confidence:.2f}"), (3, "")):
                    it = QTableWidgetItem(v)
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    self.table.setItem(i, c, it)
                item = BoxItem(i, QRectF(), self.select)
                self.scene.addItem(item)
                self._items.append(item)
                lab = QGraphicsSimpleTextItem(str(i + 1))
                lab.setBrush(QBrush(QColor(255, 255, 255)))
                self.scene.addItem(lab)
                self._labels.append(lab)
        self._place_items()
        self._refresh_sizes()

    def _place_items(self) -> None:
        if not self.project:
            return
        sel = self.current_index()
        for i, (it, lab) in enumerate(zip(self._items, self._labels)):
            b = self.project.boxes[i]
            r = self._box_rect(b)
            it.setRect(r)
            col = ON if b.vectorise else OFF
            pen = QPen(col, 3 if i == sel else 1.5)
            pen.setCosmetic(True)
            it.setPen(pen)
            fill = QColor(col)
            fill.setAlpha(60 if i == sel else 25)
            it.setBrush(fill)
            lab.setPos(r.left(), r.top() - 16)
            it.setVisible(not self._showing_result or i == sel)
            lab.setVisible(not self._showing_result)

    def _refresh_sizes(self) -> None:
        p = self.project
        if not p:
            return
        with QSignalBlocker(self.table):
            for i, b in enumerate(p.boxes):
                txt = ""
                try:
                    if b.text.strip():
                        pl = p.place(b)
                        txt = f"{pl.size_pt:.1f}" + ("" if b.size_pt else " (auto)")
                        if pl.missing_glyphs:
                            txt += " ⚠"
                except Exception:
                    txt = "?"
                self.table.item(i, 3).setText(txt)

    # ------------------------------------------------------------- selection
    def current_index(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def select(self, idx: int) -> None:
        self.table.selectRow(idx)

    def _selection_changed(self) -> None:
        i = self.current_index()
        self._place_items()
        self.editor.setEnabled(i >= 0)
        if i < 0:
            return
        b = self.project.boxes[i]
        self.view.ensureVisible(self._items[i].rect(), 80, 80)
        blockers = [QSignalBlocker(w) for w in (self.ed_text, self.ed_font, self.ed_auto,
                                                 self.ed_size, self.ed_align, self.ed_grow, self.ed_vec)]
        self.ed_vec.setChecked(b.vectorise)
        self.ed_text.setText(b.text)
        fid = b.font_id or default_font_id(b.bold_guess)
        j = self.ed_font.findData(fid)
        if j < 0:
            self.ed_font.addItem(fid.rsplit("/", 1)[-1], fid)
            j = self.ed_font.count() - 1
        self.ed_font.setCurrentIndex(j)
        auto = b.size_pt is None
        self.ed_auto.setChecked(auto)
        self.ed_size.setEnabled(not auto)
        try:
            self.ed_size.setValue(b.size_pt or self.project.place(b).size_pt)
        except Exception:
            pass
        self.ed_align.setCurrentText(b.align)
        self.ed_grow.setValue(int(round(b.mask_grow * 10)))
        del blockers
        self._update_colour_button(b.colour)
        self._update_info(b)

    def _update_colour_button(self, rgb) -> None:
        r, g, b = rgb
        fg = "#000" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#fff"
        self.ed_colour.setText(f"#{r:02x}{g:02x}{b:02x}")
        self.ed_colour.setStyleSheet(f"background:#{r:02x}{g:02x}{b:02x}; color:{fg};")

    def _update_info(self, b) -> None:
        msg = [f"OCR: “{b.ocr_text}”  (confidence {b.confidence:.2f})",
               f"Detected weight: {'bold' if b.bold_guess else 'regular'}"]
        try:
            pl = self.project.place(b)
            if pl.missing_glyphs:
                msg.append(f"<b style='color:#e55'>Font lacks glyphs: {pl.missing_glyphs}</b>")
        except Exception as e:
            msg.append(f"<b style='color:#e55'>{e}</b>")
        self.ed_info.setText("<br>".join(msg))

    # ----------------------------------------------------------------- edits
    def _cur(self):
        i = self.current_index()
        return (i, self.project.boxes[i]) if i >= 0 else (i, None)

    def _after_edit(self, i: int, b) -> None:
        self._place_items()
        self._refresh_sizes()
        self._update_info(b)
        if self.ed_auto.isChecked() and b.text.strip():
            with QSignalBlocker(self.ed_size):
                try:
                    self.ed_size.setValue(self.project.place(b).size_pt)
                except Exception:
                    pass
        self.changed.emit()

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        b = self.project.boxes[item.row()]
        if item.column() == 0:
            b.vectorise = item.checkState() == Qt.Checked
        elif item.column() == 1:
            b.text = item.text()
        if item.row() == self.current_index():
            self._selection_changed()
        self._after_edit(item.row(), b)

    def _edit_text(self, t: str) -> None:
        i, b = self._cur()
        if b is None:
            return
        b.text = t
        with QSignalBlocker(self.table):
            self.table.item(i, 1).setText(t)
        self._after_edit(i, b)

    def _edit_font(self, _=None) -> None:
        i, b = self._cur()
        fid = self.ed_font.currentData()
        if b is None or not fid:
            return
        try:
            fitz_font(fid)
        except Exception as e:
            self.ed_info.setText(f"<b style='color:#e55'>Cannot load font: {e}</b>")
            return
        b.font_id = fid
        self._after_edit(i, b)

    def _font_to_all(self) -> None:
        fid = self.ed_font.currentData()
        if not fid:
            return
        for b in self.project.boxes:
            if b.vectorise:
                b.font_id = fid
        i, b = self._cur()
        if b is not None:
            self._after_edit(i, b)

    def _edit_size(self, *_):
        i, b = self._cur()
        if b is None:
            return
        auto = self.ed_auto.isChecked()
        self.ed_size.setEnabled(not auto)
        b.size_pt = None if auto else float(self.ed_size.value())
        self._after_edit(i, b)

    def _edit_colour(self) -> None:
        i, b = self._cur()
        if b is None:
            return
        c = QColorDialog.getColor(QColor(*b.colour), self, "Text colour")
        if c.isValid():
            b.colour = (c.red(), c.green(), c.blue())
            self._update_colour_button(b.colour)
            self._after_edit(i, b)

    def _edit_align(self, a: str) -> None:
        i, b = self._cur()
        if b is not None:
            b.align = a
            self._after_edit(i, b)

    def _edit_grow(self, v: int) -> None:
        i, b = self._cur()
        if b is not None:
            b.mask_grow = v / 10.0
            self._after_edit(i, b)

    def _edit_vec(self, on: bool) -> None:
        i, b = self._cur()
        if b is None:
            return
        b.vectorise = on
        with QSignalBlocker(self.table):
            self.table.item(i, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self._after_edit(i, b)

    def _set_all(self, on: bool) -> None:
        for b in self.project.boxes:
            b.vectorise = on
        self._rebuild()
        self.changed.emit()
