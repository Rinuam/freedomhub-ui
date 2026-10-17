"""Enhancement controls: AI model/preset, factor, restoration, faces, tone & detail."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSignalBlocker, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..enhance import zoo
from ..enhance.adjust import Adjustments
from ..enhance.pipeline import EnhanceSettings

# (attr, label, min, max, scale, tooltip)
ADJ = [
    ("exposure", "Exposure", -200, 200, 100, "EV"),
    ("contrast", "Contrast", -100, 100, 100, ""),
    ("highlights", "Highlights", -100, 100, 100, "negative recovers bright areas"),
    ("shadows", "Shadows", -100, 100, 100, "positive lifts dark areas"),
    ("saturation", "Saturation", -100, 100, 100, ""),
    ("vibrance", "Vibrance", -100, 100, 100, "boosts muted colours, protects saturated ones"),
    ("warmth", "Warmth", -100, 100, 100, "blue ↔ amber"),
    ("tint", "Tint", -100, 100, 100, "green ↔ magenta"),
    ("clarity", "Clarity", 0, 100, 100, "local contrast (large radius)"),
    ("sharpen", "Sharpen", 0, 200, 100, "unsharp mask after AI upscale"),
    ("sharpen_radius", "  radius", 10, 300, 100, "in source pixels"),
    ("denoise", "Denoise", 0, 100, 100, "edge-preserving, applied after upscale"),
    ("grain", "Film grain", 0, 100, 100, "adds fine grain to avoid a plastic look"),
]


class Slider(QWidget):
    valueChanged = Signal(float)

    def __init__(self, lo, hi, scale, tip=""):
        super().__init__()
        self.scale = scale
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(lo, hi)
        self.v = QLabel("0")
        self.v.setMinimumWidth(38)
        self.v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.s, 1)
        lay.addWidget(self.v)
        self.setToolTip(tip)
        self.s.valueChanged.connect(self._ch)
        self.s.setPageStep(max(1, (hi - lo) // 20))

    def _ch(self, i):
        self.v.setText(f"{i / self.scale:+.2f}" if self.s.minimum() < 0 else f"{i / self.scale:.2f}")
        self.valueChanged.emit(i / self.scale)

    def set(self, v):
        with QSignalBlocker(self.s):
            self.s.setValue(int(round(v * self.scale)))
        self.v.setText(f"{v:+.2f}" if self.s.minimum() < 0 else f"{v:.2f}")

    def mouseDoubleClickEvent(self, ev):
        self.s.setValue(0 if self.s.minimum() <= 0 else self.s.minimum())


class EnhancePanel(QWidget):
    settingsChanged = Signal()        # AI settings (needs re-run)
    adjustChanged = Signal()          # tone/detail (live preview)
    runRequested = Signal()
    testRequested = Signal()
    modelsRequested = Signal()

    def __init__(self, s: EnhanceSettings, parent=None):
        super().__init__(parent)
        self.s = s
        self.preset = QComboBox()
        for name, (_, _, _, desc) in zoo.PRESETS.items():
            self.preset.addItem(name)
            self.preset.setItemData(self.preset.count() - 1, desc, Qt.ToolTipRole)
        self.preset.addItem("Custom")
        self.preset_desc = QLabel()
        self.preset_desc.setWordWrap(True)
        self.preset_desc.setStyleSheet("color:#888")
        self.model = QComboBox()
        self.detail = QComboBox()
        self.blend = Slider(0, 100, 100, "share of the detail model in each tile")
        self.factor = QComboBox()
        self.factor.addItem("Auto (to largest output)", "auto")
        for f in (2, 4, 8, 16):
            self.factor.addItem(f"{f}×", str(f))
        self.max_factor = QComboBox()
        for f in (4, 8, 16):
            self.max_factor.addItem(f"{f}×", f)
        self.tta = QCheckBox("Self-ensemble ×8 (TTA) — best fidelity, 8× slower")
        self.precision = QComboBox()
        self.precision.addItem("FP32 (best)", "fp32")
        self.precision.addItem("FP16 (faster, some models)", "fp16")
        self.precision.addItem("BF16", "bf16")
        self.tile = QSpinBox()
        self.tile.setRange(64, 1024)
        self.tile.setSingleStep(64)
        self.tile.setToolTip("Smaller tiles use less GPU memory")
        self.restore = QComboBox()
        self.restore.addItem("Off", "off")
        self.restore.addItem("Remove JPEG artefacts (FBCNN)", "fbcnn")
        self.restore.addItem("Denoise (SCUNet)", "scunet")
        self.restore_strength = Slider(0, 100, 100)
        self.face = QComboBox()
        self.face.addItem("Off", "off")
        self.face.addItem("GFPGAN 1.4", "gfpgan-1.4")
        self.face.addItem("CodeFormer (non-commercial licence)", "codeformer")
        self.face_strength = Slider(0, 100, 100)
        self.face_fid = Slider(0, 100, 100, "CodeFormer: 0 = most restoration, 1 = most faithful")
        self.eta = QLabel()
        self.eta.setWordWrap(True)
        self.eta.setStyleSheet("color:#888")
        self.btn_run = QPushButton("✨ Enhance with AI")
        self.btn_run.setStyleSheet("font-weight:bold; padding:8px")
        self.btn_test = QPushButton("Test on visible area")
        self.btn_test.setToolTip("Runs the current settings on a 256 px crop of what you see in the editor")
        self.btn_models = QPushButton("Models…")

        ai = QFormLayout()
        ai.addRow("Preset", self.preset)
        ai.addRow(self.preset_desc)
        ai.addRow("Model", self.model)
        ai.addRow("Detail model", self.detail)
        ai.addRow("  blend", self.blend)
        ai.addRow("Enlarge", self.factor)
        ai.addRow("Max enlarge", self.max_factor)
        ai.addRow(self.tta)
        ai.addRow("Precision", self.precision)
        ai.addRow("Tile size", self.tile)
        rest = QFormLayout()
        rest.addRow("Pre-clean", self.restore)
        rest.addRow("  strength", self.restore_strength)
        rest.addRow("Faces", self.face)
        rest.addRow("  strength", self.face_strength)
        rest.addRow("  fidelity", self.face_fid)
        self.adj_widgets = {}
        tone = QFormLayout()
        for attr, label, lo, hi, sc, tip in ADJ:
            w = Slider(lo, hi, sc, tip)
            w.valueChanged.connect(lambda v, a=attr: self._adj(a, v))
            self.adj_widgets[attr] = w
            tone.addRow(label, w)
        reset = QPushButton("Reset adjustments")
        reset.clicked.connect(self._reset_adj)
        tone.addRow(reset)

        body = QWidget()
        bl = QVBoxLayout(body)
        for title, lay in (("AI enhancement", ai), ("Restoration", rest), ("Tone and detail (live)", tone)):
            g = QGroupBox(title)
            g.setLayout(lay)
            bl.addWidget(g)
        bl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.eta)
        row = QHBoxLayout()
        row.addWidget(self.btn_test)
        row.addWidget(self.btn_models)
        outer.addLayout(row)
        outer.addWidget(self.btn_run)

        self.refresh_models()
        self.load(s)
        self.preset.activated.connect(self._preset)
        for w in (self.model, self.detail, self.factor, self.max_factor, self.precision, self.restore, self.face):
            w.activated.connect(self._store)
        for w in (self.blend, self.restore_strength, self.face_strength, self.face_fid):
            w.valueChanged.connect(self._store)
        self.tta.toggled.connect(self._store)
        self.tile.valueChanged.connect(self._store)
        self._adj_timer = QTimer(self, singleShot=True, interval=180, timeout=self.adjustChanged.emit)
        self.btn_run.clicked.connect(self.runRequested.emit)
        self.btn_test.clicked.connect(self.testRequested.emit)
        self.btn_models.clicked.connect(self.modelsRequested.emit)

    # ------------------------------------------------------------------
    def refresh_models(self) -> None:
        cur_m, cur_d = self.s.model, self.s.detail_model
        for combo, with_none in ((self.model, False), (self.detail, True)):
            with QSignalBlocker(combo):
                combo.clear()
                if with_none:
                    combo.addItem("— none —", "")
                else:
                    combo.addItem("Auto (analyse image)", "auto")
                for m in zoo.CATALOG:
                    if m.kind != "sr":
                        continue
                    mark = "" if zoo.is_installed(m.id) else "  (not installed)"
                    combo.addItem(f"{m.name}{mark}", m.id)
                for p in zoo.custom_models():
                    combo.addItem(f"Custom: {p.name}", str(p))
                if not with_none:
                    combo.addItem("Real-ESRGAN ncnn (fast, no PyTorch)", "ncnn:realesr-animevideov3")
                    combo.addItem("Lanczos (no AI)", "lanczos")
        self._select(self.model, cur_m)
        self._select(self.detail, cur_d)

    @staticmethod
    def _select(combo, data):
        i = combo.findData(data)
        with QSignalBlocker(combo):
            combo.setCurrentIndex(max(0, i))

    def load(self, s: EnhanceSettings) -> None:
        self.s = s
        with QSignalBlocker(self.preset):
            i = self.preset.findText(s.preset)
            self.preset.setCurrentIndex(i if i >= 0 else self.preset.count() - 1)
        self.preset_desc.setText(zoo.PRESETS.get(s.preset, ("", "", 0, "Custom settings"))[3])
        self._select(self.model, s.model)
        self._select(self.detail, s.detail_model)
        self.blend.set(s.detail_blend)
        self._select(self.factor, s.factor)
        self._select(self.max_factor, s.max_factor)
        with QSignalBlocker(self.tta):
            self.tta.setChecked(s.tta)
        self._select(self.precision, s.precision)
        with QSignalBlocker(self.tile):
            self.tile.setValue(s.tile)
        self._select(self.restore, s.pre_restore)
        self.restore_strength.set(s.pre_strength)
        self._select(self.face, s.face)
        self.face_strength.set(s.face_strength)
        self.face_fid.set(s.face_fidelity)
        for attr, w in self.adj_widgets.items():
            w.set(getattr(s.adjust, attr))

    def _preset(self, _=None):
        name = self.preset.currentText()
        if name in zoo.PRESETS:
            self.s.apply_preset(name)
            self.load(self.s)
            self.settingsChanged.emit()

    def _store(self, *_):
        s = self.s
        s.model = self.model.currentData()
        s.detail_model = self.detail.currentData() or ""
        s.detail_blend = self.blend.s.value() / 100
        s.factor = self.factor.currentData()
        s.max_factor = self.max_factor.currentData()
        s.tta = self.tta.isChecked()
        s.precision = self.precision.currentData()
        s.tile = self.tile.value()
        s.pre_restore = self.restore.currentData()
        s.pre_strength = self.restore_strength.s.value() / 100
        s.face = self.face.currentData()
        s.face_strength = self.face_strength.s.value() / 100
        s.face_fidelity = self.face_fid.s.value() / 100
        preset = zoo.PRESETS.get(s.preset)
        if not preset or (preset[0], preset[1], preset[2]) != (s.model, s.detail_model, s.detail_blend):
            s.preset = "Custom"
            with QSignalBlocker(self.preset):
                self.preset.setCurrentText("Custom")
            self.preset_desc.setText("Custom settings")
        self.settingsChanged.emit()

    def _adj(self, attr, v):
        setattr(self.s.adjust, attr, v)
        self._adj_timer.start()

    def _reset_adj(self):
        self.s.adjust = Adjustments()
        for attr, w in self.adj_widgets.items():
            w.set(getattr(self.s.adjust, attr))
        self.adjustChanged.emit()

    def set_eta(self, text: str) -> None:
        self.eta.setText(text)
