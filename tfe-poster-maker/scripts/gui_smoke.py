"""Headless GUI smoke test: open an image, edit a box, render, screenshot each tab.

QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py samples/portrait_poster.png out_dir
"""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tfe_poster.gui.main_window import MainWindow  # noqa: E402

img, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
app = QApplication(sys.argv)
w = MainWindow()
w.panel.upscale.setChecked("--upscale" in sys.argv)
w.resize(1600, 1000)
w.show()
w.open(img)
state = {"step": 0}


def tick():
    if w.task and w.task.isRunning():
        return
    p = w.project
    s = state["step"]
    if s == 0 and p and p.canvas is not None:
        w.review.select(0)
        app.processEvents()
        w.grab().save(str(out / "1_review.png"))
        w.review.ed_text.setText(w.review.ed_text.text() + "!")
        w.review.ed_text.textEdited.emit(w.review.ed_text.text())
        w.render_preview()
        state["step"] = 1
    elif s == 1:
        w.grab().save(str(out / "2_review_result.png"))
        w.tabs.setCurrentIndex(1)
        app.processEvents()
        w.compare.set_zoom(0.6)
        w.compare.cx, w.compare.cy = 3500, 1000
        w.compare.update()
        app.processEvents()
        w.grab().save(str(out / "3_compare.png"))
        w.tabs.setCurrentIndex(2)
        app.processEvents()
        w.grab().save(str(out / "4_report.png"))
        print("boxes:", [(b.text, b.vectorise) for b in p.boxes])
        print("OK")
        app.quit()


t = QTimer()
t.timeout.connect(tick)
t.start(300)
QTimer.singleShot(600_000, lambda: (print("TIMEOUT"), app.exit(2)))
sys.exit(app.exec())
