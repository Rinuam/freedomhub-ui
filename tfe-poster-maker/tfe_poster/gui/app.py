"""Qt application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME


class PosterApp(QApplication):
    """Handles Finder 'Open With' / drops on the Dock icon (QFileOpenEvent)."""
    window = None
    pending: list[Path] = []

    def event(self, ev):
        if ev.type() == QEvent.FileOpen:
            path = Path(ev.file())
            if self.window is not None:
                self.window.batch(str(path)) if path.is_dir() else self.window.open(path)
            else:
                self.pending.append(path)
            return True
        return super().event(ev)


def run(argv=None) -> int:
    app = QApplication.instance() or PosterApp(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Ideaded")
    icon = Path(__file__).resolve().parent.parent / "resources" / "icon.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    from .main_window import MainWindow
    w = MainWindow()
    w.show()
    if isinstance(app, PosterApp):
        app.window = w
        for p in app.pending:
            w.open(p)
    args = [a for a in (argv or sys.argv)[1:] if not a.startswith("-") and a != "gui"]
    if args and Path(args[0]).is_file():
        w.open(Path(args[0]))
    return app.exec()
