"""Headless GUI smoke test (v2): open -> edit text -> add text -> erase -> enhance -> final -> compare -> export.

QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py IMAGE OUT_DIR [--model plksr-nomos2]
"""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tfe_poster.formats import print_target, social_target  # noqa: E402
from tfe_poster.gui.main_window import MainWindow  # noqa: E402

img, out = Path(sys.argv[1]), Path(sys.argv[2])
model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "plksr-nomos2"
out.mkdir(parents=True, exist_ok=True)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: None)
errors = []
QMessageBox.critical = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a))
app = QApplication(sys.argv)
w = MainWindow()
w.resize(1700, 1000)
w.enhance.model, w.enhance.preset, w.enhance.device = model, "Custom", "auto"
w.enh_panel.load(w.enhance)
w.targets[:] = [print_target("A4", 150), social_target("Instagram post 1:1")]
w.out_panel.set_targets(w.targets)
w.out_panel.out_dir.setText(str(out / "export"))
w.show()
w.open(img)
step = {"n": 0}


def shot(name):
    app.processEvents()
    w.grab().save(str(out / name))
    print("shot", name, flush=True)


def tick():
    if w.task and w.task.isRunning():
        return
    if errors:
        print("ERRORS:", errors)
        app.exit(3)
        return
    p, n = w.project, step["n"]
    step["n"] += 1
    if n == 0:
        tp = w.text_panel
        first = next(b for b in p.blocks if b.vectorise)
        tp.select(first.id)
        w.canvas.select_block(first.id)
        tp.ed_stroke_on.setChecked(True)
        tp.ed_shadow_on.setChecked(True)
        tp.ed_track.setValue(60)
        shot("1_editor.png")
    elif n == 1:
        w._add_text(p.size[0] * 0.5, p.size[1] * 0.55)
        b = w.text_panel._cur
        w.text_panel.ed_text.setPlainText("Added vector text\nsecond line")
        w.text_panel._apply_text()
        w._erase_rect(p.size[0] * 0.05, p.size[1] * 0.40, p.size[0] * 0.12, p.size[1] * 0.12)
        shot("2_added.png")
    elif n == 2:
        w.run_enhance()
    elif n == 3:
        shot("3_enhanced.png")
        w.mode.setCurrentIndex(2)
        w._mode_changed()
    elif n == 4:
        shot("4_final_bg.png")
        w.enhance.adjust.clarity = 0.3
        w.enhance.adjust.vibrance = 0.2
        w._adjust_changed()
        w.tabs.setCurrentIndex(1)
    elif n == 5:
        w.cmp_mode.setCurrentIndex(1)
        w.update_compare()
    elif n == 6:
        w.compare.set_zoom(1.0)
        shot("5_compare.png")
        w.export()
    elif n == 7:
        shot("6_report.png")
        print(w.report.toPlainText())
        print("OK")
        app.quit()


t = QTimer()
t.timeout.connect(tick)
t.start(400)
QTimer.singleShot(3_000_000, lambda: (print("TIMEOUT"), app.exit(2)))
sys.exit(app.exec())
