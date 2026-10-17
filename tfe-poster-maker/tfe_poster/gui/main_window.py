"""Main window v2: Enhance (left) · Editor/Compare/Report (centre) · Text & Outputs (right)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QFileDialog,
                               QFormLayout, QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QTabWidget, QToolBar,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..enhance import adjust as adj
from ..enhance.pipeline import EnhanceSettings, Enhancer, estimate_seconds
from ..formats import DEFAULT_TARGETS, OutputTarget, original_target, place
from ..ocr import backend_name
from ..project import PROJECT_SUFFIX, Project, format_report
from ..text.engine import autofit
from ..text.model import EraseRegion
from .canvas import Canvas
from .compare import CompareView
from .enhance_panel import EnhancePanel
from .imageutil import downscale
from .models_dialog import ModelsDialog
from .outputs_panel import OutputsPanel
from .text_panel import TextPanel
from .workers import Task

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.PNG *.JPG *.JPEG)"
PREVIEW_SIDE = 2400
COMPARE_CAP = 8000


class BatchDialog(QDialog):
    def __init__(self, win, folder: str = ""):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Batch process folder")
        self.resize(760, 520)
        self.inp, self.out = QLineEdit(folder), QLineEdit(str(Path(folder) / "tfe_output") if folder else "")
        b1, b2 = QPushButton("…"), QPushButton("…")
        b1.clicked.connect(lambda: self._pick(self.inp))
        b2.clicked.connect(lambda: self._pick(self.out))
        self.vec = QComboBox()
        self.vec.addItem("Confident lines (≥ 0.6)", "auto")
        self.vec.addItem("All lines", "all")
        self.vec.addItem("None (keep raster text)", "none")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 11))
        self.bar = QProgressBar()
        self.go = QPushButton("Start")
        self.go.clicked.connect(self._start)
        stop = QPushButton("Stop")
        stop.clicked.connect(lambda: self.task and self.task.stop())
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        r1.addWidget(self.inp)
        r1.addWidget(b1)
        r2.addWidget(self.out)
        r2.addWidget(b2)
        f = QFormLayout()
        f.addRow("Input folder", r1)
        f.addRow("Output folder", r2)
        f.addRow("Vector text", self.vec)
        f.addRow(QLabel("Uses the current Enhance settings and the checked Outputs. "
                        "Images with saved edits (<name>.tfe.json) reuse them."))
        btn = QHBoxLayout()
        btn.addStretch(1)
        btn.addWidget(self.go)
        btn.addWidget(stop)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(self.log, 1)
        lay.addWidget(self.bar)
        lay.addLayout(btn)
        self.task = None

    def _pick(self, e):
        d = QFileDialog.getExistingDirectory(self, "Folder", e.text())
        if d:
            e.setText(d)
            if e is self.inp and not self.out.text():
                self.out.setText(str(Path(d) / "tfe_output"))

    def _start(self):
        from ..batch import find_images, run_batch
        inp = Path(self.inp.text())
        if not inp.is_dir() or not find_images(inp):
            QMessageBox.warning(self, "Batch", "Choose a folder containing images")
            return
        out = Path(self.out.text() or inp / "tfe_output")
        enh = EnhanceSettings.from_dict(self.win.enhance.to_dict())
        targets = [OutputTarget.from_dict(t.to_dict()) for t in self.win.targets]
        vec = self.vec.currentData()
        self.go.setEnabled(False)
        self.log.appendPlainText(f"{len(find_images(inp))} images -> {out}")

        def job(progress):
            return run_batch(inp, out, enh, targets, vec, "", lambda i, n, m, f: progress(m, (i + f) / n),
                             should_stop=lambda: self.task.stopping)
        self.task = Task(job, self)
        self.task.progress.connect(lambda m, f: (self.bar.setValue(int(f * 100)), self.bar.setFormat(m[:90])))
        self.task.done.connect(self._done)
        self.task.failed.connect(lambda e: (self.log.appendPlainText("FAILED: " + e), self.go.setEnabled(True)))
        self.task.start()

    def _done(self, rows):
        for r in rows:
            self.log.appendPlainText(f"{r['status']:5} {r['file']}  {r['ai']}  {r['vectorised']}/{r['text_blocks']} "
                                     "vector" + (f"\n      {r['error'].splitlines()[0]}" if r["error"] else ""))
        self.log.appendPlainText("Summary: batch_summary.csv")
        self.bar.setValue(100)
        self.go.setEnabled(True)

    def closeEvent(self, ev):
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait()
        super().closeEvent(ev)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1680, 1000)
        self.qs = QSettings("Ideaded", "TFE Poster Maker")
        try:
            self.enhance = EnhanceSettings.from_dict(json.loads(self.qs.value("enhance", "{}")))
        except Exception:
            self.enhance = EnhanceSettings()
        try:
            self.targets = [OutputTarget.from_dict(t) for t in json.loads(self.qs.value("targets", "[]"))] or \
                [OutputTarget.from_dict(t.to_dict()) for t in DEFAULT_TARGETS]
        except Exception:
            self.targets = [OutputTarget.from_dict(t.to_dict()) for t in DEFAULT_TARGETS]
        self.project: Project | None = None
        self.task: Task | None = None
        self._preview_cache = {}            # mode -> (img, px_per_src)
        self.view_mode = "original"

        # ---------------- centre
        self.canvas = Canvas()
        self.canvas.blockSelected.connect(self._canvas_selected)
        self.canvas.blockMoved.connect(self._block_moved)
        self.canvas.addTextAt.connect(self._add_text)
        self.canvas.eraseRect.connect(self._erase_rect)
        self.canvas.eraseDeleted.connect(self._erase_deleted)
        self.mode = QComboBox()
        self.mode.addItem("Original image", "original")
        self.mode.addItem("AI enhanced", "ai")
        self.mode.addItem("Final background (text removed)", "final")
        self.mode.activated.connect(self._mode_changed)
        self.show_text = QCheckBox("Vector text")
        self.show_text.setChecked(True)
        self.show_text.toggled.connect(self.canvas.set_text_visible)
        self.show_erase = QCheckBox("Erase areas")
        self.show_erase.setChecked(True)
        self.show_erase.toggled.connect(self.canvas.set_erase_visible)
        tools = QActionGroup(self)
        self.tool_btns = {}
        tbar = QHBoxLayout()
        for key, label, tip in (("select", "↖ Select/Move", "Drag text; arrows nudge (Shift = 10 px)"),
                                ("text", "T  Add text", "Click where the new text should go"),
                                ("erase", "⌫ Erase area", "Drag a rectangle to remove anything with LaMa")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self.tool_btns[key] = b
            tbar.addWidget(b)
        fitb = QPushButton("Fit")
        fitb.clicked.connect(self.canvas.fit)
        tbar.addWidget(fitb)
        tbar.addStretch(1)
        tbar.addWidget(QLabel("Show:"))
        tbar.addWidget(self.mode)
        tbar.addWidget(self.show_text)
        tbar.addWidget(self.show_erase)
        ed = QWidget()
        el = QVBoxLayout(ed)
        el.setContentsMargins(0, 0, 0, 0)
        el.addLayout(tbar)
        el.addWidget(self.canvas, 1)

        self.compare = CompareView()
        self.cmp_mode = QComboBox()
        self.cmp_mode.addItem("Original (bicubic)  vs  AI enhanced", "orig-ai")
        self.cmp_mode.addItem("Original (bicubic)  vs  Final", "orig-final")
        self.cmp_mode.addItem("AI enhanced  vs  Final", "ai-final")
        self.cmp_mode.activated.connect(lambda _: self.update_compare())
        cb = QHBoxLayout()
        for label, fn in (("Fit", self.compare.fit), ("100%", self.compare.actual),
                          ("200%", lambda: self.compare.set_zoom(2.0))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            cb.addWidget(b)
        cb.addWidget(self.cmp_mode)
        cb.addStretch(1)
        cb.addWidget(QLabel("wheel = zoom · drag = pan · drag handle = split · double-click = 100%"))
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(cb)
        cl.addWidget(self.compare, 1)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setFont(QFont("Menlo", 12))
        self.tabs = QTabWidget()
        self.tabs.addTab(ed, "Editor")
        self.tabs.addTab(cw, "Before / After")
        self.tabs.addTab(self.report, "Report")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        # ---------------- docks
        self.enh_panel = EnhancePanel(self.enhance)
        self.enh_panel.settingsChanged.connect(self._enh_changed)
        self.enh_panel.adjustChanged.connect(self._adjust_changed)
        self.enh_panel.runRequested.connect(self.run_enhance)
        self.enh_panel.testRequested.connect(self.test_region)
        self.enh_panel.modelsRequested.connect(self.models)
        self.text_panel = TextPanel()
        self.text_panel.changed.connect(self._block_changed)
        self.text_panel.structureChanged.connect(self._structure_changed)
        self.text_panel.selected.connect(lambda bid: self.canvas.select_block(bid, emit=False))
        self.text_panel.suggestRequested.connect(self.suggest_fonts)
        self.text_panel.toolRequested.connect(self.set_tool)
        self.out_panel = OutputsPanel()
        self.out_panel.set_targets(self.targets)
        self.out_panel.changed.connect(self._targets_changed)
        self.out_panel.exportRequested.connect(self.export)
        self.out_panel.out_dir.setText(self.qs.value("out_dir", ""))
        right = QTabWidget()
        right.addTab(self.text_panel, "Text")
        right.addTab(self.out_panel, "Outputs")
        self.right_tabs = right
        for title, w, area, width in (("Enhance", self.enh_panel, Qt.LeftDockWidgetArea, 390),
                                      ("Text and outputs", right, Qt.RightDockWidgetArea, 400)):
            d = QDockWidget(title)
            d.setWidget(w)
            d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
            w.setMinimumWidth(width)
            self.addDockWidget(area, d)

        # ---------------- actions
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_open = QAction("Open…", self, shortcut=QKeySequence.Open, triggered=self.open_dialog)
        self.act_save = QAction("Save edits", self, shortcut=QKeySequence.Save, triggered=self.save_edits)
        self.act_enh = QAction("✨ Enhance", self, shortcut="Ctrl+R", triggered=self.run_enhance)
        self.act_export = QAction("⬇ Export", self, shortcut="Ctrl+E", triggered=self.export)
        self.act_batch = QAction("Batch…", self, shortcut="Ctrl+B", triggered=self.batch)
        self.act_models = QAction("Models…", self, triggered=self.models)
        for a in (self.act_open, self.act_save, self.act_enh, self.act_export, self.act_batch, self.act_models):
            tb.addAction(a)
        m = self.menuBar().addMenu("File")
        for a in (self.act_open, self.act_save, self.act_export, self.act_batch):
            m.addAction(a)
        self.menuBar().addMenu("AI").addActions([self.act_enh, self.act_models])
        self.menuBar().addMenu("Help").addAction(QAction("About", self, triggered=self.about))

        self.bar = QProgressBar()
        self.bar.setMaximumWidth(460)
        self.bar.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(lambda: self.task and self.task.stop())
        self.statusBar().addPermanentWidget(self.bar)
        self.statusBar().addPermanentWidget(self.cancel_btn)
        self.statusBar().showMessage("Open an image (⌘O) or drop one here")
        self.setAcceptDrops(True)
        self._final_timer = QTimer(self, singleShot=True, interval=900, timeout=self._refresh_final)
        self.set_tool("select")
        self._enable()

    # ================================================================ helpers
    def _enable(self):
        busy = self.task is not None and self.task.isRunning()
        has = self.project is not None
        for a in (self.act_enh, self.act_export, self.act_save):
            a.setEnabled(has and not busy)
        self.enh_panel.btn_run.setEnabled(has and not busy)
        self.enh_panel.btn_test.setEnabled(has and not busy)
        self.out_panel.btn_export.setEnabled(has and not busy)
        self.act_open.setEnabled(not busy)

    def _run(self, fn, on_done, label, cancellable=True):
        if self.task and self.task.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait for the current job (or cancel it).")
            return False
        self.task = Task(fn, self)
        self.bar.show()
        self.bar.setValue(0)
        self.bar.setFormat(label)
        self.cancel_btn.setVisible(cancellable)
        self.task.progress.connect(self._progress)
        self.task.done.connect(lambda r: (self._finish(), on_done(r)))
        self.task.failed.connect(self._failed)
        self.task.start()
        self._enable()
        return True

    def _progress(self, msg, f):
        self.bar.setValue(int(f * 100))
        self.bar.setFormat(f"{msg}  %p%")
        self.statusBar().showMessage(msg)

    def _finish(self):
        self.task = None
        self.bar.hide()
        self.cancel_btn.hide()
        self._enable()

    def _failed(self, err):
        stopped = self.task is not None and self.task.stopping
        self._finish()
        if stopped or "Cancelled" in err or "InterruptedError" in err:
            self.statusBar().showMessage("Cancelled")
            return
        QMessageBox.critical(self, APP_NAME, err[:3000])

    def _save_settings(self):
        self.qs.setValue("enhance", json.dumps(self.enhance.to_dict()))
        self.qs.setValue("targets", json.dumps([t.to_dict() for t in self.targets]))
        self.qs.setValue("out_dir", self.out_panel.out_dir.text())

    def set_tool(self, key):
        self.canvas.tool = key
        for k, b in self.tool_btns.items():
            b.setChecked(k == key)
        self.canvas.setDragMode(QGraphicsView.RubberBandDrag if key == "select" else QGraphicsView.NoDrag)
        self.canvas.viewport().setCursor(Qt.CrossCursor if key != "select" else Qt.ArrowCursor)

    def _units(self):
        p = self.project
        if not p:
            return 1.0, "px"
        for t in self.targets:
            if t.enabled and t.kind == "print":
                pl = place(t, *p.size)
                return pl.scale * 72.0 / pl.dpi, f"pt on {t.name}"
        return 1.0, "px @ source"

    # ================================================================ open
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [Path(u.toLocalFile()) for u in ev.mimeData().urls()]
        if paths and paths[0].is_dir():
            self.batch(str(paths[0]))
        elif paths:
            self.open(paths[0])

    def open_dialog(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open image", self.qs.value("last_dir", str(Path.home())),
                                            IMAGE_FILTER)
        if fn:
            self.qs.setValue("last_dir", str(Path(fn).parent))
            self.open(Path(fn))

    def open(self, path: Path):
        if self.task and self.task.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait for the current job to finish.")
            return
        proj = Project(path)
        proj.enhance = self.enhance
        proj.targets = self.targets
        try:
            proj.load()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Cannot open {path.name}:\n{e}")
            return
        saved = next((p for p in (path.parent / "tfe_output" / f"{path.stem}{PROJECT_SUFFIX}",
                                  path.with_name(path.stem + PROJECT_SUFFIX)) if p.is_file()), None)
        use_saved = bool(saved) and QMessageBox.question(
            self, APP_NAME, f"Load your saved edits from\n{saved}?") == QMessageBox.Yes
        self.project = proj
        self._preview_cache = {}
        self.compare.clear()
        self.setWindowTitle(f"{APP_NAME} — {path.name}")
        self.out_panel.set_source_size(proj.size)
        if not self.out_panel.out_dir.text():
            self.out_panel.out_dir.setText(str(path.parent / "tfe_output"))

        def job(progress):
            if use_saved:
                proj.load_edits(saved, settings=False)
                proj.ocr_backend = "saved edits"
            else:
                proj.detect_text(progress)
            return proj
        self._run(job, self._opened, "Detecting text…", cancellable=False)

    def _opened(self, proj):
        self.view_mode = "original"
        self.mode.setCurrentIndex(0)
        self._set_bg()
        if any(b.erase for b in proj.blocks):      # show the clean background under the vector text
            self.mode.setCurrentIndex(2)
            self.view_mode = "final"
            QTimer.singleShot(50, self._refresh_final)
        self.canvas.set_project(proj)
        self.text_panel.set_project(proj, *self._units())
        self._update_eta()
        self.right_tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"{len(proj.blocks)} text lines found ({backend_name()}). "
                                     "Edit text, then ✨ Enhance (⌘R) and ⬇ Export (⌘E).")
        self.report.setPlainText(format_report(proj.report([])))

    # ================================================================ preview
    def _base(self, mode):
        p = self.project
        if mode in self._preview_cache:
            return self._preview_cache[mode]
        if mode == "original":
            r = downscale(p.src, PREVIEW_SIDE)
        elif mode == "ai":
            if p.master is None:
                return None
            r = p.preview_base(PREVIEW_SIDE)
        else:
            return None
        self._preview_cache[mode] = r
        return r

    def _set_bg(self):
        p = self.project
        if not p:
            return
        base = self._base(self.view_mode)
        if base is None:
            base = self._base("ai") or self._base("original")
        img, k = base
        if self.view_mode != "original":
            img = adj.apply(img, p.enhance.adjust, k)
        self.canvas.set_background(img, k)

    def _mode_changed(self, _=None):
        self.view_mode = self.mode.currentData()
        if self.view_mode == "ai" and self.project and self.project.master is None:
            self.statusBar().showMessage("Run ✨ Enhance first — showing the original for now")
        if self.view_mode == "final":
            self._refresh_final()
            return
        self._set_bg()

    def _refresh_final(self):
        p = self.project
        if not p or self.view_mode != "final":
            return
        if self.task and self.task.isRunning():
            self._final_timer.start()
            return

        def job(progress):
            return p.preview_base(PREVIEW_SIDE, cleaned=True)

        def done(r):
            self._preview_cache["final"] = r
            self._set_bg()
        self._run(job, done, "Removing text for preview…")

    def _adjust_changed(self):
        self._set_bg()
        self._save_settings()

    # ================================================================ enhance
    def _enh_changed(self):
        self._save_settings()
        self._update_eta()

    def _update_eta(self):
        p = self.project
        if not p:
            return
        try:
            enh = Enhancer(self.enhance, p.src)
            f = p.target_factor()
            mid = enh.s.model
            secs = estimate_seconds(mid, p.size[0] * p.size[1], f, self.enhance.tta,
                                    "mps" if enh.backend == "torch" else "cpu")
            if self.enhance.detail_model and self.enhance.detail_blend > 0:
                secs += estimate_seconds(self.enhance.detail_model, p.size[0] * p.size[1], f, self.enhance.tta)
            t = f"{secs / 60:.0f} min" if secs > 90 else f"{secs:.0f} s"
            out = p.size[0] * f, p.size[1] * f
            why = f"<br>{enh.auto_reason}" if enh.auto_reason else ""
            self.enh_panel.set_eta(f"Plan: {enh.describe()} → ×{f} = {out[0]}×{out[1]} px "
                                   f"({out[0] * out[1] / 1e6:.0f} MP).<br>Rough time on Apple GPU: ~{t}{why}"
                                   + ("" if enh.backend == "torch" else
                                      "<br><b>Model not installed — open Models… to download it.</b>"))
        except Exception as e:
            self.enh_panel.set_eta(f"{e}")

    def run_enhance(self):
        p = self.project
        if not p:
            return

        def job(progress):
            p.run_enhance(progress, lambda: self.task.stopping)
            return p

        def done(_):
            self._preview_cache.pop("ai", None)
            self._preview_cache.pop("final", None)
            self.view_mode = "ai"
            self.mode.setCurrentIndex(1)
            self._set_bg()
            info = p.master_info
            self.statusBar().showMessage(f"Enhanced ×{p.master_factor} with {info.get('method')} in "
                                         f"{info.get('seconds', 0)} s" + (" (cache)" if info.get("cached") else ""))
            self.report.setPlainText(format_report(p.report([])))
            self._compare_cache = {}
        self._run(job, done, "Enhancing…")

    def test_region(self):
        p = self.project
        if not p:
            return
        r = self.canvas.visible_source_rect()
        cx, cy = r.center().x(), r.center().y()
        w, h = p.size
        half = 128
        x0, y0 = int(max(0, min(w - 2 * half, cx - half))), int(max(0, min(h - 2 * half, cy - half)))
        crop = p.src[y0:y0 + 2 * half, x0:x0 + 2 * half]
        settings = EnhanceSettings.from_dict(self.enhance.to_dict())

        def job(progress):
            enh = Enhancer(settings, p.src)
            f = 4 if enh.backend != "torch" else max(2, enh.model_scale)
            res = enh.run(crop, f, progress, lambda: self.task.stopping)
            return res, f, enh.describe()

        def done(r):
            import cv2
            res, f, name = r
            bic = cv2.resize(crop, (res.image.shape[1], res.image.shape[0]), interpolation=cv2.INTER_CUBIC)
            self.compare.set_images(bic, res.image, ("Bicubic", f"{name} (test ×{f}, {res.seconds:.1f} s)"))
            self.tabs.setCurrentIndex(1)
            self.compare.fit()
        self._run(job, done, "Testing on region…")

    # ================================================================ text
    def _canvas_selected(self, bid):
        self.right_tabs.setCurrentIndex(0)
        self.text_panel.select(bid)

    def _block_moved(self, bid):
        b = self.text_panel.block(bid)
        if b is self.text_panel._cur:
            self.text_panel.load_block(b)

    def _block_changed(self, bid):
        b = self.text_panel.block(bid)
        if b is None:
            return
        it = self.canvas.text_items.get(bid)
        if it is not None and b.vectorise:
            it.rebuild()
        else:
            self.canvas.refresh_block(b)
        if self.view_mode == "final":
            self._final_timer.start()

    def _structure_changed(self):
        self.canvas.rebuild_items()
        self.text_panel.rebuild_list()
        self._preview_cache.pop("final", None)
        if self.view_mode == "final":
            self._final_timer.start()

    def _add_text(self, x, y):
        b = self.project.new_block(x, y)
        self.canvas.rebuild_items()
        self.text_panel.rebuild_list(b.id)
        self.canvas.select_block(b.id)
        self.set_tool("select")
        self.text_panel.ed_text.setFocus()
        self.text_panel.ed_text.selectAll()

    def _erase_rect(self, x, y, w, h):
        self.project.erase_regions.append(EraseRegion(x, y, w, h))
        self._structure_changed()

    def _erase_deleted(self, region):
        if region in self.project.erase_regions:
            self.project.erase_regions.remove(region)
        self._structure_changed()

    def suggest_fonts(self, bid):
        p = self.project
        b = self.text_panel.block(bid)
        if not p or b is None or b.user_added:
            self.statusBar().showMessage("Font suggestions need a detected text line")
            return
        from ..text.fontmatch import suggest

        def job(progress):
            return suggest(p.src, b, 12, lambda f: progress("Comparing fonts…", f), lambda: self.task.stopping)
        self._run(job, self.text_panel.show_suggestions, "Comparing fonts…")

    # ================================================================ outputs
    def _targets_changed(self):
        self.targets = self.out_panel.targets
        if self.project:
            self.project.targets = self.targets
            self.text_panel.set_units(*self._units())
            self._update_eta()
        self._save_settings()

    def export(self):
        p = self.project
        if not p:
            return
        if not any(t.enabled for t in self.targets):
            QMessageBox.information(self, APP_NAME, "Check at least one output in the Outputs tab.")
            self.right_tabs.setCurrentIndex(1)
            return
        out = self.out_panel.out_dir.text() or str(p.source_path.parent / "tfe_output")
        self._save_settings()
        need_ai = p.master is None
        if need_ai and QMessageBox.question(
                self, APP_NAME, "The image has not been AI-enhanced yet. Enhance now before exporting?\n"
                                "(No = export using plain resampling)") == QMessageBox.Yes:
            pass
        else:
            need_ai = False

        def job(progress):
            if need_ai:
                p.run_enhance(lambda m, f: progress(m, 0.7 * f), lambda: self.task.stopping)
                return p.export(Path(out), lambda m, f: progress(m, 0.7 + 0.3 * f), lambda: self.task.stopping)
            return p.export(Path(out), progress, lambda: self.task.stopping)

        def done(rep):
            self.report.setPlainText(format_report(rep))
            self.tabs.setCurrentIndex(2)
            self._preview_cache.pop("ai", None)
            if self.view_mode == "original" and p.master is not None:
                self.mode.setCurrentIndex(1)
                self.view_mode = "ai"
            self._set_bg()
            warn = "\n".join(rep.get("warnings", []))
            QMessageBox.information(self, APP_NAME, f"Exported {len(rep['outputs'])} files to\n{out}"
                                    + (f"\n\n{warn}" if warn else ""))
        self._run(job, done, "Exporting…")

    # ================================================================ compare
    def _tab_changed(self, i):
        if i == 1:
            self.update_compare()

    def update_compare(self):
        import cv2
        p = self.project
        if not p:
            return
        mode = self.cmp_mode.currentData()
        if p.master is None:
            self.compare.clear()
            self.statusBar().showMessage("Run ✨ Enhance to compare")
            return
        cache = getattr(self, "_compare_cache", None)
        if cache is None or cache.get("_id") != id(p.master):
            cache = self._compare_cache = {"_id": id(p.master)}
        ai, k = downscale(p.master, COMPARE_CAP)
        h, w = ai.shape[:2]
        if "orig" not in cache:
            cache["orig"] = cv2.resize(p.src, (w, h), interpolation=cv2.INTER_CUBIC)
        if "ai" not in cache:
            cache["ai"] = adj.apply(ai, p.enhance.adjust, w / p.size[0])
        if mode == "orig-ai":
            self.compare.set_images(cache["orig"], cache["ai"], ("Original (bicubic)", "AI enhanced"))
            return
        key = ("final", json.dumps([b.to_dict() for b in p.blocks], default=str),
               json.dumps(p.enhance.adjust.to_dict()), len(p.erase_regions))
        if cache.get("final_key") == key:
            a, b = (cache["orig"], cache["final"]) if mode == "orig-final" else (cache["ai"], cache["final"])
            self.compare.set_images(a, b, ("Original (bicubic)" if mode == "orig-final" else "AI enhanced", "Final"))
            return
        t = original_target(max(w, h), ["png"])

        def job(progress):
            return p.render_target(t, progress, lambda: self.task.stopping).flat

        def done(flat):
            cache["final"], cache["final_key"] = flat, key
            self.update_compare()
        self._run(job, done, "Rendering final for comparison…")

    # ================================================================ misc
    def save_edits(self):
        p = self.project
        if not p:
            return
        out = Path(self.out_panel.out_dir.text() or p.source_path.parent / "tfe_output")
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{p.source_path.stem}{PROJECT_SUFFIX}"
        p.save(path)
        self.statusBar().showMessage(f"Saved edits to {path}")

    def batch(self, folder: str = ""):
        BatchDialog(self, folder).exec()

    def models(self):
        ModelsDialog(self).exec()
        self.enh_panel.refresh_models()
        self._update_eta()

    def about(self):
        import platform
        from ..enhance.torch_sr import torch_available, device_name
        dev = device_name() if torch_available() else "no PyTorch"
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b> {__version__}<br>"
                          "AI enhancement up to 16× (DRCT-L, HAT-L, DAT2…), LaMa text removal, "
                          "editable vector text, print & social exports. Runs offline.<br><br>"
                          f"Compute: {dev} · OCR: {backend_name()} · {platform.platform()}")

    def closeEvent(self, ev):
        self._save_settings()
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait(5000)
        super().closeEvent(ev)
