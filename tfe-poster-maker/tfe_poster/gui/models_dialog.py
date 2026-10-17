"""Model manager: download (checksum-verified), delete, import custom spandrel models."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..enhance import zoo
from .workers import Task


class ModelsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI models")
        self.resize(1050, 560)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Model", "Type", "Arch", "Size", "Speed", "Licence", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.table.itemSelectionChanged.connect(self._info)
        self.bar = QProgressBar()
        self.bar.hide()
        self.btn_dl = QPushButton("Download selected")
        self.btn_rec = QPushButton("Download recommended set")
        self.btn_del = QPushButton("Delete")
        self.btn_imp = QPushButton("Import model file…")
        self.btn_imp.setToolTip("Any .pth/.safetensors that spandrel supports (e.g. from openmodeldb.info)")
        self.btn_dir = QPushButton("Open models folder")
        close = QPushButton("Close")
        self.btn_dl.clicked.connect(lambda: self._download(self._selected()))
        self.btn_rec.clicked.connect(lambda: self._download([m for m in zoo.DEFAULT_BUNDLE
                                                            if not zoo.is_installed(m)]))
        self.btn_del.clicked.connect(self._delete)
        self.btn_imp.clicked.connect(self._import)
        self.btn_dir.clicked.connect(lambda: (zoo.user_dir().mkdir(parents=True, exist_ok=True),
                                              QDesktopServices.openUrl(QUrl.fromLocalFile(str(zoo.user_dir())))))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        for b in (self.btn_dl, self.btn_rec, self.btn_del, self.btn_imp, self.btn_dir):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Downloads happen once; afterwards everything runs offline. "
                             f"Models are stored in: {zoo.user_dir()}"))
        lay.addWidget(self.table, 1)
        lay.addWidget(self.info)
        lay.addWidget(self.bar)
        lay.addLayout(row)
        self.task = None
        self.refresh()

    def refresh(self):
        rows = [(m.id, m) for m in zoo.CATALOG] + [(str(p), None) for p in zoo.custom_models()]
        self.table.setRowCount(len(rows))
        for r, (mid, m) in enumerate(rows):
            if m is None:
                p = Path(mid)
                vals = [f"Custom: {p.name}", "sr", "?", f"{p.stat().st_size / 1e6:.0f} MB", "", "your file", "installed"]
            else:
                vals = [m.name, m.kind, m.arch, f"{m.size_mb:.0f} MB", "●" * m.speed,
                        m.license + ("" if m.commercial_ok else " ⚠"),
                        "installed" if zoo.is_installed(m.id) else ("recommended" if m.id in zoo.DEFAULT_BUNDLE else "—")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, mid)
                if c == 6 and v == "installed":
                    it.setForeground(Qt.darkGreen)
                if c == 5 and m is not None and not m.commercial_ok:
                    it.setForeground(Qt.red)
                self.table.setItem(r, c, it)

    def _selected(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            mid = self.table.item(idx.row(), 0).data(Qt.UserRole)
            if mid in zoo.BY_ID and not zoo.is_installed(mid):
                ids.append(mid)
        return ids

    def _info(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        mid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        m = zoo.BY_ID.get(mid)
        if m:
            self.info.setText(f"<b>{m.name}</b> — {m.best_for}. {m.notes}<br>"
                              f"<span style='color:#888'>{m.url}</span>")

    def _download(self, ids):
        if not ids:
            QMessageBox.information(self, "Models", "Nothing to download (already installed or none selected).")
            return
        total = sum(zoo.BY_ID[i].size for i in ids)

        def job(progress):
            done = 0
            for mid in ids:
                m = zoo.BY_ID[mid]
                zoo.download(mid, lambda f, d=done, m=m: progress(f"Downloading {m.name}…", (d + f * m.size) / total),
                             should_stop=lambda: self.task.stopping)
                done += m.size
            return ids
        self.bar.show()
        for b in (self.btn_dl, self.btn_rec, self.btn_del):
            b.setEnabled(False)
        self.task = Task(job, self)
        self.task.progress.connect(lambda m, f: (self.bar.setValue(int(f * 100)), self.bar.setFormat(f"{m} %p%")))
        self.task.done.connect(self._done)
        self.task.failed.connect(lambda e: (QMessageBox.critical(self, "Download failed", e[:1500]), self._done(None)))
        self.task.start()

    def _done(self, _):
        self.bar.hide()
        for b in (self.btn_dl, self.btn_rec, self.btn_del):
            b.setEnabled(True)
        self.refresh()

    def _delete(self):
        rows = self.table.selectionModel().selectedRows()
        for idx in rows:
            mid = self.table.item(idx.row(), 0).data(Qt.UserRole)
            p = zoo.model_path(mid)
            if p and str(zoo.user_dir()) in str(p):
                p.unlink()
            elif p:
                QMessageBox.information(self, "Models", f"{p.name} is bundled with the app and can't be deleted.")
        self.refresh()

    def _import(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import model", str(Path.home()),
                                            "Models (*.pth *.safetensors *.ckpt)")
        if not fn:
            return
        try:
            zoo.import_model(Path(fn))
        except Exception as e:
            QMessageBox.critical(self, "Import failed", f"spandrel could not load this file:\n{e}")
            return
        self.refresh()

    def closeEvent(self, ev):
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait()
        super().closeEvent(ev)
