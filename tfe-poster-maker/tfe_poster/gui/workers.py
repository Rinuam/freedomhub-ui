"""Run pipeline steps off the UI thread."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class Task(QThread):
    progress = Signal(str, float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[str, float], None]], Any], parent=None):
        super().__init__(parent)
        self._fn = fn
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    @property
    def stopping(self) -> bool:
        return self._stop

    def run(self) -> None:
        try:
            res = self._fn(lambda m, f: self.progress.emit(m, float(f)))
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")
            return
        self.done.emit(res)
