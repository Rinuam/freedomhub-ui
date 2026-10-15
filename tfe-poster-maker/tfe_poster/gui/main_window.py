"""Main window: settings, review, compare, report, batch."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QKeySequence, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QTabWidget, QToolBar, QVBoxLayout, QWidget,
                               QDockWidget)

from .. import APP_NAME, __version__
from ..config import Settings, UPSCALE_MODELS
from ..ocr import backend_name
from ..project import Project, SIDE_CAR_SUFFIX, format_report
from ..upscale import find_realesrgan
from .compare import CompareView
from .review import ReviewPanel
from .workers import Task

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.PNG *.JPG *.JPEG)"


class SettingsPanel(QWidget):
    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.orient = QComboBox()
        self.orient.addItems(["auto", "portrait", "landscape"])
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 150)
        self.margin.setSuffix(" mm")
        self.upscale = QCheckBox("Real-ESRGAN 4x")
        self.model = QComboBox()
        for k, v in UPSCALE_MODELS.items():
            self.model.addItem(v, k)
        self.inpaint = QComboBox()
        self.inpaint.addItem("Telea (fast, smooth)", "telea")
        self.inpaint.addItem("Navier-Stokes", "ns")
        self.pdfbg = QComboBox()
        self.pdfbg.addItem("JPEG q95 (smaller PDF)", "jpeg")
        self.pdfbg.addItem("Lossless (large PDF)", "lossless")
        self.vec_default = QComboBox()
        self.vec_default.addItem("Confident boxes", "auto")
        self.vec_default.addItem("All boxes", "all")
        self.vec_default.addItem("None", "none")
        esr = find_realesrgan(s.realesrgan_path)
        self.esr_label = QLabel(f"Real-ESRGAN: {'found' if esr else '<b>not found</b> - Lanczos fallback'}")
        self.esr_label.setWordWrap(True)
        self.ocr_label = QLabel(f"OCR: {backend_name()}")
        self.reprocess = QPushButton("Apply && re-process")
        f = QFormLayout(self)
        f.addRow("Orientation", self.orient)
        f.addRow("Margin", self.margin)
        f.addRow("Upscale", self.upscale)
        f.addRow("Model", self.model)
        f.addRow("Inpaint", self.inpaint)
        f.addRow("PDF background", self.pdfbg)
        f.addRow("Vectorise by default", self.vec_default)
        f.addRow(self.reprocess)
        f.addRow(self.esr_label)
        f.addRow(self.ocr_label)
        self.load(s)

    def load(self, s: Settings) -> None:
        self.orient.setCurrentText(s.orientation)
        self.margin.setValue(s.margin_mm)
        self.upscale.setChecked(s.upscale)
        self.model.setCurrentIndex(max(0, self.model.findData(s.upscale_model)))
        self.inpaint.setCurrentIndex(max(0, self.inpaint.findData(s.inpaint_method)))
        self.pdfbg.setCurrentIndex(max(0, self.pdfbg.findData(s.pdf_background)))
        self.vec_default.setCurrentIndex(max(0, self.vec_default.findData(s.batch_vectorise)))

    def store(self, s: Settings) -> Settings:
        s.orientation = self.orient.currentText()
        s.margin_mm = self.margin.value()
        s.upscale = self.upscale.isChecked()
        s.upscale_model = self.model.currentData()
        s.inpaint_method = self.inpaint.currentData()
        s.pdf_background = self.pdfbg.currentData()
        s.batch_vectorise = self.vec_default.currentData()
        return s


class BatchDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch process folder")
        self.resize(720, 480)
        self.settings = settings
        self.inp = QLineEdit()
        self.out = QLineEdit()
        b1, b2 = QPushButton("…"), QPushButton("…")
        b1.clicked.connect(lambda: self._pick(self.inp))
        b2.clicked.connect(lambda: self._pick(self.out))
        self.vec = QComboBox()
        self.vec.addItem("Confident boxes (>= 0.6)", "auto")
        self.vec.addItem("All boxes", "all")
        self.vec.addItem("None (raster only)", "none")
        self.vec.setCurrentIndex(max(0, self.vec.findData(settings.batch_vectorise)))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 11))
        self.bar = QProgressBar()
        self.go = QPushButton("Start")
        self.go.clicked.connect(self._start)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        r1.addWidget(self.inp)
        r1.addWidget(b1)
        r2.addWidget(self.out)
        r2.addWidget(b2)
        form = QFormLayout()
        form.addRow("Input folder", r1)
        form.addRow("Output folder", r2)
        form.addRow("Vector text", self.vec)
        form.addRow(QLabel("Images with saved review edits (<name>.tfe.json) reuse them."))
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(self.go)
        btns.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.log, 1)
        lay.addWidget(self.bar)
        lay.addLayout(btns)
        self.task = None

    def _pick(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
        if d:
            edit.setText(d)
            if edit is self.inp and not self.out.text():
                self.out.setText(str(Path(d) / "tfe_output"))

    def _start(self) -> None:
        from ..batch import run_batch, find_images
        inp = Path(self.inp.text())
        if not inp.is_dir():
            QMessageBox.warning(self, "Batch", "Choose an input folder")
            return
        out = Path(self.out.text() or inp / "tfe_output")
        n = len(find_images(inp))
        if not n:
            QMessageBox.warning(self, "Batch", "No PNG/JPG images in that folder")
            return
        s = Settings.from_dict(self.settings.to_dict())
        s.batch_vectorise = self.vec.currentData()
        self.go.setEnabled(False)
        self.log.appendPlainText(f"Processing {n} images -> {out}")

        def job(progress):
            return run_batch(inp, out, s,
                             lambda i, n, m, f: progress(m, (i + f) / n),
                             should_stop=lambda: self.task.stopping)
        self.task = Task(job, self)
        self.task.progress.connect(lambda m, f: (self.bar.setValue(int(f * 100)), self.bar.setFormat(m)))
        self.task.done.connect(self._done)
        self.task.failed.connect(lambda e: (self.log.appendPlainText("FAILED: " + e), self.go.setEnabled(True)))
        self.task.start()

    def _done(self, rows) -> None:
        for r in rows:
            self.log.appendPlainText(
                f"{r['status']:5}  {r['file']}  native {r['native_ppi']} -> effective "
                f"{r['effective_ppi']} ppi, {r['vectorised']}/{r['text_boxes']} vector"
                + (f"\n       {r['error'].splitlines()[0]}" if r["error"] else ""))
        self.log.appendPlainText("Summary written to batch_summary.csv")
        self.bar.setValue(100)
        self.bar.setFormat("Done")
        self.go.setEnabled(True)

    def closeEvent(self, ev) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            self.log.appendPlainText("Stopping after the current image…")
            self.task.wait()
        super().closeEvent(ev)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 950)
        self.qs = QSettings("Ideaded", "TFE Poster Maker")
        try:
            import json
            self.settings = Settings.from_dict(json.loads(self.qs.value("settings", "{}")))
        except Exception:
            self.settings = Settings()
        self.project: Project | None = None
        self.task: Task | None = None
        self._preview_stale = True

        self.review = ReviewPanel()
        self.review.renderRequested.connect(self.render_preview)
        self.review.changed.connect(self._mark_stale)
        self.compare = CompareView()
        self.cmp_mode = QComboBox()
        self.cmp_mode.addItem("Plain bicubic  vs  final", "naive")
        self.cmp_mode.addItem("Upscaled raster (text untouched)  vs  final", "canvas")
        self.cmp_mode.addItem("Plain bicubic  vs  upscaled raster", "upscale")
        self.cmp_mode.currentIndexChanged.connect(self._update_compare)
        cmp_bar = QHBoxLayout()
        for label, fn in (("Fit", self.compare.fit), ("100%", self.compare.actual),
                          ("400%", lambda: self.compare.set_zoom(4.0))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            cmp_bar.addWidget(b)
        cmp_bar.addWidget(self.cmp_mode)
        cmp_bar.addStretch(1)
        cmp_bar.addWidget(QLabel("Wheel: zoom · drag: pan · drag the handle: split · double-click: 100%"))
        cmp_w = QWidget()
        cl = QVBoxLayout(cmp_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(cmp_bar)
        cl.addWidget(self.compare, 1)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setFont(QFont("Menlo", 12))

        self.tabs = QTabWidget()
        self.tabs.addTab(self.review, "Review")
        self.tabs.addTab(cmp_w, "Before / After")
        self.tabs.addTab(self.report, "DPI report")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        self.panel = SettingsPanel(self.settings)
        self.panel.reprocess.clicked.connect(self.reprocess)
        dock = QDockWidget("Settings")
        dock.setWidget(self.panel)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_open = QAction("Open image…", self, shortcut=QKeySequence.Open, triggered=self.open_dialog)
        self.act_batch = QAction("Batch folder…", self, shortcut="Ctrl+B", triggered=self.batch)
        self.act_render = QAction("Render preview", self, shortcut="Ctrl+R", triggered=self.render_preview)
        self.act_export = QAction("Export PDF + PNG…", self, shortcut="Ctrl+E", triggered=self.export)
        for a in (self.act_open, self.act_batch, self.act_render, self.act_export):
            tb.addAction(a)
        m = self.menuBar().addMenu("File")
        for a in (self.act_open, self.act_batch, self.act_render, self.act_export):
            m.addAction(a)
        self.menuBar().addMenu("Help").addAction(QAction("About", self, triggered=self.about))

        self.bar = QProgressBar()
        self.bar.setMaximumWidth(420)
        self.bar.setTextVisible(True)
        self.bar.hide()
        self.statusBar().addPermanentWidget(self.bar)
        self._enable(False)
        self.setAcceptDrops(True)
        self.statusBar().showMessage("Open an image (⌘O) or drop one here")

    # ---------------------------------------------------------------- helpers
    def _enable(self, has_project: bool) -> None:
        busy = self.task is not None and self.task.isRunning()
        ready = has_project and self.project is not None and self.project.canvas is not None
        self.act_render.setEnabled(ready and not busy)
        self.act_export.setEnabled(ready and not busy)
        self.act_open.setEnabled(not busy)
        self.review.btn_render.setEnabled(ready and not busy)
        self.panel.reprocess.setEnabled(has_project and not busy)

    def _run(self, fn, on_done, label: str) -> None:
        self.task = Task(fn, self)
        self.bar.show()
        self.bar.setValue(0)
        self.bar.setFormat(label)
        self.task.progress.connect(self._progress)
        self.task.done.connect(lambda r: (self._finish(), on_done(r)))
        self.task.failed.connect(self._failed)
        self.task.start()
        self._enable(True)

    def _progress(self, msg: str, f: float) -> None:
        self.bar.setValue(int(f * 100))
        self.bar.setFormat(f"{msg}  %p%")
        self.statusBar().showMessage(msg)

    def _finish(self) -> None:
        self.task = None
        self.bar.hide()
        self._enable(self.project is not None)

    def _failed(self, err: str) -> None:
        self._finish()
        QMessageBox.critical(self, APP_NAME, err[:3000])

    def _save_settings(self) -> None:
        import json
        self.qs.setValue("settings", json.dumps(self.settings.to_dict()))

    def _mark_stale(self) -> None:
        self._preview_stale = True

    # ------------------------------------------------------------------ open
    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        paths = [Path(u.toLocalFile()) for u in ev.mimeData().urls()]
        if paths and paths[0].is_dir():
            self.batch(str(paths[0]))
        elif paths:
            self.open(paths[0])

    def open_dialog(self) -> None:
        start = self.qs.value("last_dir", str(Path.home()))
        fn, _ = QFileDialog.getOpenFileName(self, "Open image", start, IMAGE_FILTER)
        if fn:
            self.qs.setValue("last_dir", str(Path(fn).parent))
            self.open(Path(fn))

    def open(self, path: Path) -> None:
        if self.task and self.task.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait for the current step to finish.")
            return
        self.settings = self.panel.store(self.settings)
        self._save_settings()
        proj = Project(path, Settings.from_dict(self.settings.to_dict()))
        try:
            proj.load()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Cannot open {path.name}:\n{e}")
            return
        self.project = proj
        self.compare.clear()
        self.setWindowTitle(f"{APP_NAME} — {path.name}")
        sidecar = self._find_sidecar(path)
        use_saved = False
        if sidecar:
            use_saved = QMessageBox.question(
                self, APP_NAME, f"Load saved review edits from\n{sidecar}?") == QMessageBox.Yes

        def job(progress):
            if use_saved:
                proj.load_sidecar(sidecar)
                proj.ocr_backend = "saved edits"
            else:
                proj.detect_text(lambda m, f: progress(m, 0.05 * f))
            progress("Text detected - upscaling…", 0.05)
            return proj
        self._run(job, self._ocr_done, "Detecting text…")

    def _find_sidecar(self, path: Path):
        for p in (path.parent / "tfe_output" / f"{path.stem}{SIDE_CAR_SUFFIX}",
                  path.with_name(path.stem + SIDE_CAR_SUFFIX)):
            if p.is_file():
                return p
        return None

    def _ocr_done(self, proj) -> None:
        self.review.set_project(proj)
        self.report.setPlainText(f"{len(proj.boxes)} text boxes. Upscaling…")
        self._prepare()

    def _prepare(self) -> None:
        proj = self.project
        self._preview_stale = True

        def job(progress):
            proj.prepare(progress)
            return proj
        self._run(job, self._prepared, "Upscaling…")

    def _prepared(self, proj) -> None:
        self.review.refresh_background()
        self.report.setPlainText(format_report(proj.dpi_report()))
        self.statusBar().showMessage(
            f"Ready: {proj.upscale_method}. Review boxes, then Render preview (⌘R) or Export (⌘E).")

    def reprocess(self) -> None:
        if not self.project:
            return
        old = self.project
        self.settings = self.panel.store(self.settings)
        self._save_settings()
        boxes = old.boxes
        proj = Project(old.source_path, Settings.from_dict(self.settings.to_dict()))
        proj.load()
        proj.boxes, proj.ocr_backend = boxes, old.ocr_backend
        self.project = proj
        self.review.set_project(proj)
        self.compare.clear()
        self._prepare()

    # ---------------------------------------------------------------- render
    def render_preview(self, then=None) -> None:
        if not self.project or self.project.canvas is None:
            return
        proj = self.project
        self.settings = self.panel.store(self.settings)
        proj.settings.inpaint_method = self.settings.inpaint_method

        def job(progress):
            return proj.render(progress)
        self._run(job, lambda r: self._rendered(r, then), "Rendering…")

    def _rendered(self, res, then=None) -> None:
        _, placements, flat = res
        self._preview_stale = False
        self.review.set_result_preview(flat)
        self._update_compare()
        self.report.setPlainText(format_report(self.project.dpi_report(placements)))
        missing = [p for p in placements if p.missing_glyphs]
        msg = "Preview rendered"
        if missing:
            msg += f" - {len(missing)} box(es) use a font missing glyphs"
        self.statusBar().showMessage(msg)
        if then:
            then()
        elif self.tabs.currentIndex() == 0:
            self.review.show_result.setChecked(True)

    def _update_compare(self) -> None:
        p = self.project
        cache = getattr(p, "_render_cache", None) if p else None
        if not p or p.canvas is None:
            return
        mode = self.cmp_mode.currentData()
        if not hasattr(p, "_naive") or p._naive is None:
            p._naive = p.naive_before()
        if mode == "upscale":
            self.compare.set_images(p._naive, p.canvas, ("Plain bicubic", "Upscaled"), p.layout.dpi)
            return
        if not cache:
            self.compare.clear()
            return
        flat = cache[1][2]
        before = p._naive if mode == "naive" else p.canvas
        lab = "Plain bicubic" if mode == "naive" else "Upscaled raster"
        self.compare.set_images(before, flat, (lab, "Final"), p.layout.dpi)

    def _tab_changed(self, i: int) -> None:
        if i == 1 and self.project and self.project.canvas is not None:
            if self._preview_stale and not (self.task and self.task.isRunning()) \
                    and self.cmp_mode.currentData() != "upscale":
                self.render_preview()
            else:
                self._update_compare()

    # ---------------------------------------------------------------- export
    def export(self) -> None:
        if not self.project or self.project.canvas is None:
            return
        proj = self.project
        start = str(proj.source_path.parent / "tfe_output")
        d = QFileDialog.getExistingDirectory(self, "Export to folder", start)
        if not d:
            return
        self.settings = self.panel.store(self.settings)
        proj.settings.inpaint_method = self.settings.inpaint_method
        proj.settings.pdf_background = self.settings.pdf_background

        def job(progress):
            return proj.export(Path(d), progress)

        def done(rep):
            self._rendered(proj.render(), then=lambda: None)
            self.report.setPlainText(format_report(rep))
            self.tabs.setCurrentIndex(2)
            QMessageBox.information(self, APP_NAME, "Exported:\n" + rep["outputs"]["pdf"] + "\n"
                                    + rep["outputs"]["png"])
        self._run(job, done, "Exporting…")

    def batch(self, folder: str | None = None) -> None:
        self.settings = self.panel.store(self.settings)
        self._save_settings()
        dlg = BatchDialog(Settings.from_dict(self.settings.to_dict()), self)
        if folder:
            dlg.inp.setText(folder)
            dlg.out.setText(str(Path(folder) / "tfe_output"))
        dlg.exec()

    def about(self) -> None:
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME}</b> {__version__}<br>"
                          "A1 posters from AI images: Real-ESRGAN upscaling, Apple Vision OCR, "
                          "vector text, 300 dpi export.<br>Runs fully offline.<br><br>"
                          f"OCR: {backend_name()}<br>Real-ESRGAN: {find_realesrgan() or 'not found'}")

    def closeEvent(self, ev) -> None:
        self.settings = self.panel.store(self.settings)
        self._save_settings()
        if self.task and self.task.isRunning():
            self.task.wait()
        super().closeEvent(ev)
