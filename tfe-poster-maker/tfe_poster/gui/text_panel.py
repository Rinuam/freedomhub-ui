"""Text blocks list + full typography/style editor."""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal, QSignalBlocker, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QCompleter,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QVBoxLayout, QWidget, QButtonGroup, QToolButton, QMenu)

from ..fonts import default_font_id, font_by_id, list_fonts
from ..text.engine import autofit, layout


def _dspin(lo, hi, step=1.0, dec=1, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class ColourButton(QPushButton):
    changed = Signal(tuple)

    def __init__(self, title="Colour"):
        super().__init__()
        self.title = title
        self.rgb = (0, 0, 0)
        self.clicked.connect(self._pick)
        self.setMinimumWidth(90)

    def set(self, rgb):
        self.rgb = tuple(rgb)
        r, g, b = self.rgb
        fg = "#000" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#fff"
        self.setText(f"#{r:02x}{g:02x}{b:02x}")
        self.setStyleSheet(f"background:#{r:02x}{g:02x}{b:02x}; color:{fg}; border:1px solid #888;"
                           "border-radius:4px; padding:3px")

    def _pick(self):
        c = QColorDialog.getColor(QColor(*self.rgb), self, self.title)
        if c.isValid():
            self.set((c.red(), c.green(), c.blue()))
            self.changed.emit(self.rgb)


class TextPanel(QWidget):
    changed = Signal(int)            # block id (geometry/style changed)
    structureChanged = Signal()      # blocks added/removed/merged/vectorise toggled
    selected = Signal(int)
    suggestRequested = Signal(int)
    toolRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.pt_per_src = 1.0
        self.size_unit = "px"
        self._cur = None
        self._families: dict[str, list] = {}

        # ---------------- list + actions
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._sel_changed)
        self.list.itemChanged.connect(self._item_checked)
        self.list.setMinimumHeight(140)
        bar = QHBoxLayout()
        for label, slot, tip in (("＋ Text", lambda: self.toolRequested.emit("text"), "Click on the canvas to add text"),
                                 ("Merge", self._merge, "Merge selected lines into one multi-line block"),
                                 ("Duplicate", self._duplicate, "Duplicate selected block"),
                                 ("Delete", self._delete, "Delete selected block(s)")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        allv = QPushButton("Vectorise all")
        allv.clicked.connect(lambda: self._set_all(True))
        nonev = QPushButton("None")
        nonev.clicked.connect(lambda: self._set_all(False))
        bar2 = QHBoxLayout()
        bar2.addWidget(allv)
        bar2.addWidget(nonev)
        bar2.addStretch(1)

        # ---------------- text
        self.ed_text = QPlainTextEdit()
        self.ed_text.setFixedHeight(64)
        self.ed_text.textChanged.connect(self._debounced_text)
        self._text_timer = QTimer(self, singleShot=True, interval=250, timeout=self._apply_text)
        self.ed_case = QComboBox()
        self.ed_case.addItems(["none", "upper", "lower", "title"])
        self.ed_vec = QCheckBox("Vector text")
        self.ed_erase = QCheckBox("Erase original")
        self.ed_grow = QSlider(Qt.Horizontal)
        self.ed_grow.setRange(5, 40)
        g_text = QFormLayout()
        g_text.addRow(self.ed_text)
        r = QHBoxLayout()
        r.addWidget(self.ed_vec)
        r.addWidget(self.ed_erase)
        g_text.addRow(r)
        g_text.addRow("Erase grow", self.ed_grow)
        g_text.addRow("Case", self.ed_case)

        # ---------------- font
        self.ed_family = QComboBox()
        self.ed_family.setEditable(True)
        self.ed_family.setInsertPolicy(QComboBox.NoInsert)
        self.ed_family.setMaxVisibleItems(30)
        self.ed_family.completer().setFilterMode(Qt.MatchContains)
        self.ed_family.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.ed_style = QComboBox()
        self.ed_size = _dspin(1, 5000, 1, 1)
        self.btn_fit = QPushButton("Fit to original")
        self.btn_fit.setToolTip("Size & position the vector text exactly over the detected lettering")
        self.btn_suggest = QPushButton("Suggest matching fonts…")
        self.suggest_list = QListWidget()
        self.suggest_list.setMaximumHeight(120)
        self.suggest_list.hide()
        self.suggest_list.itemClicked.connect(self._apply_suggestion)
        self.ed_track = _dspin(-300, 1500, 5, 0, " ‰")
        self.ed_lh = _dspin(0.5, 4, 0.05, 2, " ×")
        self.ed_align = QComboBox()
        self.ed_align.addItems(["center", "left", "right"])
        self.ed_bold = QSlider(Qt.Horizontal)
        self.ed_bold.setRange(0, 100)
        self.ed_italic = QCheckBox("Slant (synthetic italic)")
        self.ed_kern = QCheckBox("Kerning")
        self.ed_liga = QCheckBox("Ligatures")
        self.btn_style_all = QPushButton("Apply this style to …")
        menu = QMenu(self)
        menu.addAction("all vector blocks", lambda: self._style_to("all"))
        menu.addAction("selected blocks", lambda: self._style_to("selected"))
        menu.addAction("font only → all", lambda: self._style_to("font"))
        self.btn_style_all.setMenu(menu)
        g_font = QFormLayout()
        g_font.addRow("Family", self.ed_family)
        g_font.addRow("Style", self.ed_style)
        rs = QHBoxLayout()
        rs.addWidget(self.ed_size, 1)
        rs.addWidget(self.btn_fit)
        self.size_label = QLabel("Size")
        g_font.addRow(self.size_label, rs)
        g_font.addRow(self.btn_suggest)
        g_font.addRow(self.suggest_list)
        g_font.addRow("Tracking", self.ed_track)
        g_font.addRow("Line height", self.ed_lh)
        g_font.addRow("Align", self.ed_align)
        g_font.addRow("Extra bold", self.ed_bold)
        rk = QHBoxLayout()
        rk.addWidget(self.ed_italic)
        g_font.addRow(rk)
        rk2 = QHBoxLayout()
        rk2.addWidget(self.ed_kern)
        rk2.addWidget(self.ed_liga)
        g_font.addRow(rk2)
        g_font.addRow(self.btn_style_all)

        # ---------------- paint
        self.ed_fill = ColourButton("Text colour")
        self.ed_fill_op = QSlider(Qt.Horizontal)
        self.ed_fill_op.setRange(0, 100)
        self.ed_stroke_on = QCheckBox("Outline")
        self.ed_stroke = ColourButton("Outline colour")
        self.ed_stroke_w = _dspin(0, 50, 0.5, 1, " % em")
        self.ed_stroke_op = QSlider(Qt.Horizontal)
        self.ed_stroke_op.setRange(0, 100)
        self.ed_shadow_on = QCheckBox("Shadow")
        self.ed_shadow = ColourButton("Shadow colour")
        self.ed_shadow_op = QSlider(Qt.Horizontal)
        self.ed_shadow_op.setRange(0, 100)
        self.ed_sdx = _dspin(-100, 100, 0.5, 1, " % em")
        self.ed_sdy = _dspin(-100, 100, 0.5, 1, " % em")
        self.ed_sblur = _dspin(0, 100, 0.5, 1, " % em")
        g_paint = QFormLayout()
        rf = QHBoxLayout()
        rf.addWidget(self.ed_fill)
        rf.addWidget(QLabel("opacity"))
        rf.addWidget(self.ed_fill_op, 1)
        g_paint.addRow("Fill", rf)
        ro = QHBoxLayout()
        ro.addWidget(self.ed_stroke_on)
        ro.addWidget(self.ed_stroke)
        g_paint.addRow(ro)
        g_paint.addRow("  width", self.ed_stroke_w)
        g_paint.addRow("  opacity", self.ed_stroke_op)
        rsh = QHBoxLayout()
        rsh.addWidget(self.ed_shadow_on)
        rsh.addWidget(self.ed_shadow)
        g_paint.addRow(rsh)
        g_paint.addRow("  opacity", self.ed_shadow_op)
        rxy = QHBoxLayout()
        rxy.addWidget(self.ed_sdx)
        rxy.addWidget(self.ed_sdy)
        g_paint.addRow("  offset x / y", rxy)
        g_paint.addRow("  softness", self.ed_sblur)

        # ---------------- geometry
        self.ed_x = _dspin(-1e5, 1e5, 1, 1, " px")
        self.ed_y = _dspin(-1e5, 1e5, 1, 1, " px")
        self.ed_rot = _dspin(-180, 180, 0.5, 1, " °")
        g_geo = QFormLayout()
        rp = QHBoxLayout()
        rp.addWidget(self.ed_x)
        rp.addWidget(self.ed_y)
        g_geo.addRow("Centre x / y", rp)
        g_geo.addRow("Rotation", self.ed_rot)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)

        editor = QWidget()
        el = QVBoxLayout(editor)
        for title, lay in (("Text", g_text), ("Font and typography", g_font), ("Colour, outline and shadow", g_paint),
                           ("Position", g_geo)):
            gb = QGroupBox(title)
            gb.setLayout(lay)
            el.addWidget(gb)
        el.addWidget(self.info)
        el.addStretch(1)
        self.editor = editor
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(editor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(bar)
        lay.addWidget(self.list)
        lay.addLayout(bar2)
        lay.addWidget(scroll, 1)
        editor.setEnabled(False)
        self._wire()

    # ----------------------------------------------------------- wiring
    def _wire(self):
        def bind(w, attr, conv=lambda v: v, sig=None):
            s = sig or (w.valueChanged if hasattr(w, "valueChanged") else w.toggled)
            s.connect(lambda v, a=attr, c=conv: self._set(a, c(v)))
        self.ed_case.currentTextChanged.connect(lambda v: self._set("case", v))
        bind(self.ed_vec, "vectorise")
        bind(self.ed_erase, "erase")
        bind(self.ed_grow, "erase_mask_grow", lambda v: v / 10)
        self.ed_family.activated.connect(self._family_changed)
        self.ed_style.activated.connect(self._style_changed)
        self.ed_size.valueChanged.connect(self._size_changed)
        self.btn_fit.clicked.connect(self._fit)
        self.btn_suggest.clicked.connect(lambda: self._cur and self.suggestRequested.emit(self._cur.id))
        bind(self.ed_track, "tracking")
        bind(self.ed_lh, "line_height")
        self.ed_align.currentTextChanged.connect(lambda v: self._set("align", v))
        bind(self.ed_bold, "synth_bold", lambda v: v / 100)
        bind(self.ed_italic, "synth_italic")
        bind(self.ed_kern, "kerning")
        bind(self.ed_liga, "ligatures")
        self.ed_fill.changed.connect(lambda v: self._set("fill", v))
        bind(self.ed_fill_op, "fill_opacity", lambda v: v / 100)
        bind(self.ed_stroke_on, "stroke_on")
        self.ed_stroke.changed.connect(lambda v: self._set("stroke", v))
        bind(self.ed_stroke_w, "stroke_width")
        bind(self.ed_stroke_op, "stroke_opacity", lambda v: v / 100)
        bind(self.ed_shadow_on, "shadow_on")
        self.ed_shadow.changed.connect(lambda v: self._set("shadow", v))
        bind(self.ed_shadow_op, "shadow_opacity", lambda v: v / 100)
        bind(self.ed_sdx, "shadow_dx")
        bind(self.ed_sdy, "shadow_dy")
        bind(self.ed_sblur, "shadow_blur")
        bind(self.ed_x, "cx")
        bind(self.ed_y, "cy")
        bind(self.ed_rot, "rotation")

    def _ensure_fonts(self):
        if self._families:
            return
        fam = defaultdict(list)
        for f in list_fonts():
            fam[f.family].append(f)
        self._families = dict(sorted(fam.items(), key=lambda kv: kv[0].lower()))
        with QSignalBlocker(self.ed_family):
            for name in self._families:
                self.ed_family.addItem(name)

    # ----------------------------------------------------------- data
    def set_project(self, project, pt_per_src: float = 1.0, unit: str = "px") -> None:
        self._ensure_fonts()
        self.project = project
        self.set_units(pt_per_src, unit)
        self.rebuild_list()

    def set_units(self, pt_per_src: float, unit: str) -> None:
        self.pt_per_src, self.size_unit = pt_per_src, unit
        self.size_label.setText(f"Size ({unit})")
        if self._cur:
            self.load_block(self._cur)

    def rebuild_list(self, keep_id=None) -> None:
        keep_id = keep_id if keep_id is not None else (self._cur.id if self._cur else None)
        with QSignalBlocker(self.list):
            self.list.clear()
            for b in self.project.blocks if self.project else []:
                it = QListWidgetItem(self._row_text(b))
                it.setData(Qt.UserRole, b.id)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if b.vectorise else Qt.Unchecked)
                self.list.addItem(it)
        if keep_id is not None:
            self.select(keep_id)
        else:
            self._cur = None
            self.editor.setEnabled(False)

    def _row_text(self, b) -> str:
        t = b.text.replace("\n", " ⏎ ")
        tag = "＋" if b.user_added else f"{b.confidence:.2f}"
        warn = " ⚠" if b.vectorise and b.text.strip() and layout(b).missing else ""
        return f"{t[:48]}   [{tag}]{warn}"

    def refresh_row(self, b) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == b.id:
                with QSignalBlocker(self.list):
                    it.setText(self._row_text(b))
                    it.setCheckState(Qt.Checked if b.vectorise else Qt.Unchecked)

    def block(self, bid):
        return next((b for b in self.project.blocks if b.id == bid), None) if self.project else None

    def selected_ids(self) -> list[int]:
        return [it.data(Qt.UserRole) for it in self.list.selectedItems()]

    def select(self, bid: int) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == bid:
                if not it.isSelected() or len(self.list.selectedItems()) != 1:
                    with QSignalBlocker(self.list):
                        self.list.clearSelection()
                        it.setSelected(True)
                    self.list.scrollToItem(it)
                b = self.block(bid)
                if b is not self._cur:
                    self.load_block(b)
                return

    def _sel_changed(self):
        ids = self.selected_ids()
        if len(ids) >= 1:
            b = self.block(ids[-1])
            self.load_block(b)
            self.selected.emit(b.id)

    def _item_checked(self, it):
        b = self.block(it.data(Qt.UserRole))
        if b is None:
            return
        on = it.checkState() == Qt.Checked
        if on != b.vectorise:
            b.vectorise = on
            if not b.user_added:
                b.erase = on
            self.load_block(b)
            self.structureChanged.emit()

    def load_block(self, b) -> None:
        self._cur = b
        self.editor.setEnabled(b is not None)
        if b is None:
            return
        ws = [self.ed_text, self.ed_case, self.ed_vec, self.ed_erase, self.ed_grow, self.ed_family, self.ed_style,
              self.ed_size, self.ed_track, self.ed_lh, self.ed_align, self.ed_bold, self.ed_italic, self.ed_kern,
              self.ed_liga, self.ed_fill_op, self.ed_stroke_on, self.ed_stroke_w, self.ed_stroke_op,
              self.ed_shadow_on, self.ed_shadow_op, self.ed_sdx, self.ed_sdy, self.ed_sblur, self.ed_x, self.ed_y,
              self.ed_rot]
        blockers = [QSignalBlocker(w) for w in ws]
        if self.ed_text.toPlainText() != b.text:
            self.ed_text.setPlainText(b.text)
        self.ed_case.setCurrentText(b.case)
        self.ed_vec.setChecked(b.vectorise)
        self.ed_erase.setChecked(b.erase)
        self.ed_erase.setEnabled(not b.user_added)
        self.ed_grow.setValue(int(round(b.erase_mask_grow * 10)))
        fid = b.font_id or default_font_id(b.bold_guess)
        fi = font_by_id(fid)
        if fi:
            self.ed_family.setCurrentText(fi.family)
            self._fill_styles(fi.family, fid)
        self.ed_size.setValue(b.size * self.pt_per_src)
        self.ed_track.setValue(b.tracking)
        self.ed_lh.setValue(b.line_height)
        self.ed_align.setCurrentText(b.align)
        self.ed_bold.setValue(int(b.synth_bold * 100))
        self.ed_italic.setChecked(b.synth_italic)
        self.ed_kern.setChecked(b.kerning)
        self.ed_liga.setChecked(b.ligatures)
        self.ed_fill.set(b.fill)
        self.ed_fill_op.setValue(int(b.fill_opacity * 100))
        self.ed_stroke_on.setChecked(b.stroke_on)
        self.ed_stroke.set(b.stroke)
        self.ed_stroke_w.setValue(b.stroke_width)
        self.ed_stroke_op.setValue(int(b.stroke_opacity * 100))
        self.ed_shadow_on.setChecked(b.shadow_on)
        self.ed_shadow.set(b.shadow)
        self.ed_shadow_op.setValue(int(b.shadow_opacity * 100))
        self.ed_sdx.setValue(b.shadow_dx)
        self.ed_sdy.setValue(b.shadow_dy)
        self.ed_sblur.setValue(b.shadow_blur)
        self.ed_x.setValue(b.cx)
        self.ed_y.setValue(b.cy)
        self.ed_rot.setValue(b.rotation)
        del blockers
        self.btn_fit.setEnabled(b.ink is not None)
        self.suggest_list.hide()
        self._update_info(b)

    def _fill_styles(self, family, current_id=None):
        with QSignalBlocker(self.ed_style):
            self.ed_style.clear()
            for f in self._families.get(family, []):
                self.ed_style.addItem(f.style or "Regular", f.id)
            if current_id:
                i = self.ed_style.findData(current_id)
                if i >= 0:
                    self.ed_style.setCurrentIndex(i)

    def _update_info(self, b):
        msg = []
        if b.ocr_text and not b.user_added:
            msg.append(f"Detected: “{b.ocr_text.replace(chr(10), ' / ')}” (confidence {b.confidence:.2f}, "
                       f"{'bold' if b.bold_guess else 'regular'} weight)")
        try:
            if b.vectorise and b.text.strip():
                miss = layout(b).missing
                if miss:
                    msg.append(f"<b style='color:#e55'>This font lacks: {miss}</b> — pick another font")
        except Exception as e:
            msg.append(f"<b style='color:#e55'>{e}</b>")
        self.info.setText("<br>".join(msg))

    # ----------------------------------------------------------- edits
    def _emit(self, b):
        self.refresh_row(b)
        self._update_info(b)
        self.changed.emit(b.id)

    def _set(self, attr, value):
        b = self._cur
        if b is None:
            return
        if attr in ("cx", "cy", "rotation"):
            b.auto_fit = False
        if attr == "vectorise" and not b.user_added:
            b.erase = value
            with QSignalBlocker(self.ed_erase):
                self.ed_erase.setChecked(value)
        setattr(b, attr, value)
        if attr in ("vectorise",):
            self.refresh_row(b)
            self.structureChanged.emit()
            return
        self._emit(b)

    def _debounced_text(self):
        self._text_timer.start()

    def _apply_text(self):
        b = self._cur
        if b is None:
            return
        t = self.ed_text.toPlainText()
        if t != b.text:
            b.text = t
            if b.auto_fit and "\n" not in t:
                autofit(b)
                self._sync_geo(b)
            self._emit(b)

    def _sync_geo(self, b):
        for w, v in ((self.ed_size, b.size * self.pt_per_src), (self.ed_x, b.cx), (self.ed_y, b.cy)):
            with QSignalBlocker(w):
                w.setValue(v)

    def _family_changed(self, _=None):
        fam = self.ed_family.currentText()
        if fam not in self._families:
            return
        b = self._cur
        cur = font_by_id(b.font_id) if b else None
        faces = self._families[fam]
        want = (cur.style if cur else "Regular").lower()
        pick = next((f for f in faces if (f.style or "").lower() == want), None) or \
            next((f for f in faces if (f.style or "").lower() in ("regular", "book", "roman")), faces[0])
        self._fill_styles(fam, pick.id)
        self._set_font(pick.id)

    def _style_changed(self, _=None):
        fid = self.ed_style.currentData()
        if fid:
            self._set_font(fid)

    def _set_font(self, fid):
        b = self._cur
        if b is None:
            return
        b.font_id = fid
        if b.auto_fit:
            autofit(b)
            self._sync_geo(b)
        self._emit(b)

    def _size_changed(self, v):
        b = self._cur
        if b is None:
            return
        b.size = v / max(1e-9, self.pt_per_src)
        b.auto_fit = False
        self._emit(b)

    def _fit(self):
        b = self._cur
        if b and b.ink:
            b.auto_fit = True
            autofit(b)
            self._sync_geo(b)
            with QSignalBlocker(self.ed_rot):
                b.rotation = 0
                self.ed_rot.setValue(0)
            self._emit(b)

    def show_suggestions(self, results) -> None:
        self.suggest_list.clear()
        for fid, score in results:
            f = font_by_id(fid)
            it = QListWidgetItem(f"{f.label if f else fid}   ({score * 100:.0f}% match)")
            it.setData(Qt.UserRole, fid)
            self.suggest_list.addItem(it)
        self.suggest_list.setVisible(bool(results))

    def _apply_suggestion(self, it):
        fid = it.data(Qt.UserRole)
        f = font_by_id(fid)
        if f:
            with QSignalBlocker(self.ed_family):
                self.ed_family.setCurrentText(f.family)
            self._fill_styles(f.family, fid)
        self._set_font(fid)

    def _style_to(self, which):
        src = self._cur
        if src is None:
            return
        ids = set(self.selected_ids())
        for b in self.project.blocks:
            if b is src or not b.vectorise:
                continue
            if which == "selected" and b.id not in ids:
                continue
            if which == "font":
                b.font_id = src.font_id
            else:
                b.copy_style_from(src)
            if b.auto_fit:
                autofit(b)
        self.structureChanged.emit()

    def _set_all(self, on):
        for b in self.project.blocks:
            b.vectorise = on
            if not b.user_added:
                b.erase = on
        self.rebuild_list()
        self.structureChanged.emit()

    def _merge(self):
        ids = self.selected_ids()
        if len(ids) < 2:
            return
        m = self.project.merge_blocks(ids)
        if m:
            self.rebuild_list(m.id)
            self.structureChanged.emit()

    def _duplicate(self):
        b = self._cur
        if b is None:
            return
        import copy
        n = copy.deepcopy(b)
        n.id = max(x.id for x in self.project.blocks) + 1
        n.cy += b.size * 1.3
        n.user_added, n.erase, n.auto_fit = True, False, False
        self.project.blocks.append(n)
        self.rebuild_list(n.id)
        self.structureChanged.emit()

    def _delete(self):
        ids = set(self.selected_ids())
        if not ids:
            return
        for b in list(self.project.blocks):
            if b.id in ids:
                if b.user_added:
                    self.project.blocks.remove(b)
                else:            # detected text: keep the raster version, just stop vectorising
                    b.vectorise = b.erase = False
        self._cur = None
        self.rebuild_list()
        self.structureChanged.emit()
