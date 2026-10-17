"""Output targets: A-sizes / US / custom print, social media and original-aspect exports."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..formats import (IMAGE_FORMATS, PAPER_MM, SOCIAL_PX, OutputTarget, original_target, place,
                       print_target, social_target)


class OutputsPanel(QWidget):
    changed = Signal()
    exportRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.targets: list[OutputTarget] = []
        self.src_size = (1024, 1536)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._checked)
        self.list.currentRowChanged.connect(self._load)
        add = QPushButton("＋ Add output")
        m = QMenu(self)
        pm = m.addMenu("Print (PDF + image)")
        for p in PAPER_MM:
            pm.addAction(p, lambda p=p: self._add(print_target(p)))
        pm.addAction("Custom size (mm)…", lambda: self._add(OutputTarget(name="Custom", kind="print",
                                                                          paper="Custom", w_mm=500, h_mm=700)))
        sm = m.addMenu("Social media / screen")
        for s in SOCIAL_PX:
            sm.addAction(s, lambda s=s: self._add(social_target(s)))
        sm.addAction("Custom pixels…", lambda: self._add(OutputTarget(name="Custom px", kind="pixels",
                                                                       w_px=2000, h_px=2000, fit="extend",
                                                                       formats=["png", "jpg"])))
        om = m.addMenu("Original aspect (long side)")
        for n in (2048, 4096, 8192, 16384):
            om.addAction(f"{n} px", lambda n=n: self._add(original_target(n, ["png", "jpg"])))
        add.setMenu(m)
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove)
        top = QHBoxLayout()
        top.addWidget(add)
        top.addWidget(rem)

        # editor
        self.name = QLineEdit()
        self.paper = QComboBox()
        self.paper.addItems(list(PAPER_MM) + ["Custom"])
        self.w_mm = QDoubleSpinBox()
        self.h_mm = QDoubleSpinBox()
        for w in (self.w_mm, self.h_mm):
            w.setRange(10, 5000)
            w.setSuffix(" mm")
            w.setDecimals(1)
        self.orient = QComboBox()
        self.orient.addItems(["auto", "portrait", "landscape"])
        self.dpi = QComboBox()
        for d in (150, 200, 240, 300, 360, 400, 600):
            self.dpi.addItem(f"{d} dpi", d)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 200)
        self.margin.setSuffix(" mm")
        self.bleed = QDoubleSpinBox()
        self.bleed.setRange(0, 20)
        self.bleed.setSuffix(" mm")
        self.bleed.setToolTip("Extra image beyond the trim edge for professional printing (trim box is set)")
        self.w_px = QSpinBox()
        self.h_px = QSpinBox()
        self.long_px = QSpinBox()
        for w in (self.w_px, self.h_px, self.long_px):
            w.setRange(64, 32768)
            w.setSuffix(" px")
        self.margin_px = QSpinBox()
        self.margin_px.setRange(0, 4000)
        self.margin_px.setSuffix(" px")
        self.fit = QComboBox()
        self.fit.addItem("Fit – whole image, colour margins", "fit")
        self.fit.addItem("Extend – whole image, blurred background", "extend")
        self.fit.addItem("Fill – crop to fill the frame", "fill")
        self.focus_x = QDoubleSpinBox()
        self.focus_y = QDoubleSpinBox()
        for w in (self.focus_x, self.focus_y):
            w.setRange(0, 1)
            w.setSingleStep(0.05)
        self.bg = QComboBox()
        self.bg.addItem("Edge colour (sampled)", "edge")
        self.bg.addItem("White", "white")
        self.bg.addItem("Black", "black")
        self.bg.setEditable(True)
        self.fmt_boxes = {}
        fmts = QHBoxLayout()
        for f in ("pdf",) + IMAGE_FORMATS:
            c = QCheckBox(f.upper())
            self.fmt_boxes[f] = c
            fmts.addWidget(c)
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.pdfbg = QComboBox()
        self.pdfbg.addItem("JPEG q-setting (smaller)", "jpeg")
        self.pdfbg.addItem("Lossless (largest)", "lossless")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color:#888")

        self.form_print = QFormLayout()
        self.form_print.addRow("Paper", self.paper)
        wh = QHBoxLayout()
        wh.addWidget(self.w_mm)
        wh.addWidget(self.h_mm)
        self.form_print.addRow("Size", wh)
        self.form_print.addRow("Orientation", self.orient)
        self.form_print.addRow("Resolution", self.dpi)
        self.form_print.addRow("Margin", self.margin)
        self.form_print.addRow("Bleed", self.bleed)
        self.form_px = QFormLayout()
        whp = QHBoxLayout()
        whp.addWidget(self.w_px)
        whp.addWidget(self.h_px)
        self.form_px.addRow("Size", whp)
        self.form_px.addRow("Margin", self.margin_px)
        self.form_orig = QFormLayout()
        self.form_orig.addRow("Long side", self.long_px)
        common = QFormLayout()
        common.addRow("Name", self.name)
        common.addRow("Framing", self.fit)
        fxy = QHBoxLayout()
        fxy.addWidget(self.focus_x)
        fxy.addWidget(self.focus_y)
        common.addRow("Crop focus x / y", fxy)
        common.addRow("Background", self.bg)
        common.addRow("Formats", fmts)
        common.addRow("JPEG/WebP quality", self.quality)
        common.addRow("PDF background", self.pdfbg)
        self.g_print, self.g_px, self.g_orig = QGroupBox("Print"), QGroupBox("Pixels"), QGroupBox("Original aspect")
        self.g_print.setLayout(self.form_print)
        self.g_px.setLayout(self.form_px)
        self.g_orig.setLayout(self.form_orig)
        g_common = QGroupBox("Output")
        g_common.setLayout(common)
        body = QWidget()
        bl = QVBoxLayout(body)
        for g in (self.g_print, self.g_px, self.g_orig, g_common):
            bl.addWidget(g)
        bl.addWidget(self.summary)
        bl.addStretch(1)
        self.editor = body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        self.out_dir = QLineEdit()
        pick = QPushButton("…")
        pick.clicked.connect(self._pick_dir)
        od = QHBoxLayout()
        od.addWidget(QLabel("Folder"))
        od.addWidget(self.out_dir, 1)
        od.addWidget(pick)
        self.btn_export = QPushButton("⬇ Export all checked outputs")
        self.btn_export.setStyleSheet("font-weight:bold; padding:8px")
        self.btn_export.clicked.connect(self.exportRequested.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(self.list)
        lay.addWidget(scroll, 1)
        lay.addLayout(od)
        lay.addWidget(self.btn_export)

        for w in (self.w_mm, self.h_mm, self.margin, self.bleed, self.focus_x, self.focus_y):
            w.valueChanged.connect(self._store)
        for w in (self.w_px, self.h_px, self.long_px, self.margin_px, self.quality):
            w.valueChanged.connect(self._store)
        for w in (self.orient, self.dpi, self.fit, self.pdfbg):
            w.activated.connect(self._store)
        self.paper.activated.connect(self._paper)
        self.bg.currentTextChanged.connect(self._store)
        self.name.editingFinished.connect(self._store)
        for c in self.fmt_boxes.values():
            c.toggled.connect(self._store)

    # ------------------------------------------------------------------
    def set_targets(self, targets: list[OutputTarget], src_size=None) -> None:
        self.targets = targets
        if src_size:
            self.src_size = src_size
        self._rebuild()

    def _rebuild(self, row: int = 0):
        with QSignalBlocker(self.list):
            self.list.clear()
            for t in self.targets:
                it = QListWidgetItem(t.label())
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if t.enabled else Qt.Unchecked)
                self.list.addItem(it)
        if self.targets:
            self.list.setCurrentRow(min(row, len(self.targets) - 1))
            self._load(self.list.currentRow())
        self.editor.setEnabled(bool(self.targets))

    def _add(self, t: OutputTarget):
        self.targets.append(t)
        self._rebuild(len(self.targets) - 1)
        self.changed.emit()

    def _remove(self):
        r = self.list.currentRow()
        if 0 <= r < len(self.targets):
            self.targets.pop(r)
            self._rebuild(max(0, r - 1))
            self.changed.emit()

    def _checked(self, it):
        r = self.list.row(it)
        self.targets[r].enabled = it.checkState() == Qt.Checked
        self.changed.emit()

    def current(self):
        r = self.list.currentRow()
        return self.targets[r] if 0 <= r < len(self.targets) else None

    def _load(self, row):
        t = self.current()
        if t is None:
            return
        ws = [self.name, self.paper, self.w_mm, self.h_mm, self.orient, self.dpi, self.margin, self.bleed,
              self.w_px, self.h_px, self.long_px, self.margin_px, self.fit, self.focus_x, self.focus_y, self.bg,
              self.quality, self.pdfbg] + list(self.fmt_boxes.values())
        bl = [QSignalBlocker(w) for w in ws]
        self.g_print.setVisible(t.kind == "print")
        self.g_px.setVisible(t.kind == "pixels")
        self.g_orig.setVisible(t.kind == "original")
        self.name.setText(t.name)
        self.paper.setCurrentText(t.paper if t.paper in PAPER_MM else "Custom")
        self.w_mm.setValue(t.w_mm)
        self.h_mm.setValue(t.h_mm)
        self.orient.setCurrentText(t.orientation)
        i = self.dpi.findData(t.dpi)
        if i < 0:
            self.dpi.addItem(f"{t.dpi} dpi", t.dpi)
            i = self.dpi.count() - 1
        self.dpi.setCurrentIndex(i)
        self.margin.setValue(t.margin_mm)
        self.bleed.setValue(t.bleed_mm)
        self.w_px.setValue(t.w_px)
        self.h_px.setValue(t.h_px)
        self.long_px.setValue(t.long_side_px)
        self.margin_px.setValue(t.margin_px)
        self.fit.setCurrentIndex(max(0, self.fit.findData(t.fit)))
        self.focus_x.setValue(t.focus_x)
        self.focus_y.setValue(t.focus_y)
        j = self.bg.findData(t.background)
        if j >= 0:
            self.bg.setCurrentIndex(j)
        else:
            self.bg.setEditText(t.background)
        for f, c in self.fmt_boxes.items():
            c.setChecked(f in t.formats)
        self.quality.setValue(t.jpeg_quality)
        self.pdfbg.setCurrentIndex(max(0, self.pdfbg.findData(t.pdf_background)))
        del bl
        self._summary(t)

    def _paper(self, _=None):
        t = self.current()
        p = self.paper.currentText()
        if t and p in PAPER_MM:
            t.paper = p
            t.w_mm, t.h_mm = PAPER_MM[p]
            if t.name in PAPER_MM or t.name == "Custom":
                t.name = p
            self._load(self.list.currentRow())
            self._store()
        elif t:
            t.paper = "Custom"

    def _store(self, *_):
        t = self.current()
        if t is None:
            return
        t.name = self.name.text() or t.name
        t.w_mm, t.h_mm = self.w_mm.value(), self.h_mm.value()
        t.orientation = self.orient.currentText()
        t.dpi = int(self.dpi.currentData())
        t.margin_mm, t.bleed_mm = self.margin.value(), self.bleed.value()
        t.w_px, t.h_px = self.w_px.value(), self.h_px.value()
        t.long_side_px = self.long_px.value()
        t.margin_px = self.margin_px.value()
        t.fit = self.fit.currentData()
        t.focus_x, t.focus_y = self.focus_x.value(), self.focus_y.value()
        bg = self.bg.currentData() if self.bg.currentIndex() >= 0 and \
            self.bg.currentText() == self.bg.itemText(self.bg.currentIndex()) else self.bg.currentText()
        t.background = bg or "edge"
        t.formats = [f for f, c in self.fmt_boxes.items() if c.isChecked()] or ["png"]
        t.jpeg_quality = self.quality.value()
        t.pdf_background = self.pdfbg.currentData()
        it = self.list.currentItem()
        if it:
            with QSignalBlocker(self.list):
                it.setText(t.label())
        self._summary(t)
        self.changed.emit()

    def _summary(self, t):
        pl = place(t, *self.src_size)
        native = pl.dpi / pl.scale
        txt = f"Canvas {pl.canvas_w} × {pl.canvas_h} px ({pl.canvas_w * pl.canvas_h / 1e6:.1f} MP). " \
              f"Source is enlarged {pl.scale:.2f}× (native {native:.0f} ppi)."
        if t.kind == "print":
            txt += f" Physical: {pl.canvas_w / pl.dpi * 25.4:.0f} × {pl.canvas_h / pl.dpi * 25.4:.0f} mm."
        if "webp" in t.formats and max(pl.canvas_w, pl.canvas_h) > 16383:
            txt += " ⚠ WebP is limited to 16383 px — it will be skipped."
        self.summary.setText(txt)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def set_source_size(self, size):
        self.src_size = size
        t = self.current()
        if t:
            self._summary(t)
