# TFE Poster Maker

Turn AI-generated images (e.g. ChatGPT 1024 × 1536 PNG/JPG) into print-ready **A1 posters**:
a 300 dpi raster background, upscaled with Real-ESRGAN, with the image's text replaced
by **real vector text** in the PDF. A native macOS app (Python + PySide6) for Apple
Silicon. It runs **fully offline**.

```
image ──► fit to A1 (no crop/stretch) + margin in the image's edge colour
      ──► Real-ESRGAN 4x (ncnn/Metal via MoltenVK) ──► resample to exactly 300 dpi
      ──► Apple Vision OCR: text boxes, text, size, colour, weight
      ──► Review: edit text · pick font · size · colour · vectorise on/off per box
      ──► vectorised boxes: OpenCV inpaint of the raster text + vector text placed on top
      ──► Export: A1 PDF (embedded, subsetted fonts) + flattened 300 dpi PNG + dpi report
```

## Install (pre-built app)

1. Copy **TFE Poster Maker.app** to `/Applications`.
2. The first time, right-click → **Open** (the app is ad-hoc signed, not notarised).

## Build the .app yourself (one time, needs internet only for this step)

Requirements: macOS 12+ on Apple Silicon and Python 3.11–3.13 (python.org or Homebrew).

```bash
cd tfe-poster-maker
scripts/build_app.sh            # -> dist/TFE Poster Maker.app
scripts/build_app.sh --dmg      # also builds dist/TFE-Poster-Maker.dmg
```

The script creates `.venv`, installs the requirements (PySide6, OpenCV, PyMuPDF, pyobjc
Vision, …), downloads the Real-ESRGAN ncnn macOS build into `vendor/realesrgan`
(`scripts/fetch_realesrgan.sh`), draws the icon, and runs PyInstaller with
`packaging/tfe_poster.spec`. It then ad-hoc codesigns the bundle and runs
`TFE Poster Maker doctor` as a self-check. The bundle contains everything; after the
build, nothing touches the network.

### Run from source (no bundle)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mac.txt
scripts/fetch_realesrgan.sh
python -m tfe_poster            # GUI
python -m tfe_poster doctor     # shows OCR backend, Real-ESRGAN, fonts
```

## Using the app

1. **Open image…** (⌘O), or drop a PNG/JPG on the window or the Dock icon. OCR runs
   first (about 1 s), then the image is upscaled and placed on the sheet. The progress
   bar is at the bottom right.
2. **Settings** (left panel): orientation (auto / portrait / landscape), margin in mm,
   Real-ESRGAN model, inpainting method, PDF background encoding, and which boxes
   start out vectorised. Click **Apply & re-process** after changing the geometry or
   the upscaler; your box edits are kept.
3. **Review** tab. Every detected text line has a box: green = vectorise, orange =
   keep as raster. Click a box or a table row, then edit:
   * **Text**: fix OCR errors or rewrite the text.
   * **Font**: any installed font (type to search; `.ttc` faces are supported). Use
     **Use this font for all vectorised boxes** for consistency.
   * **Size**: *Auto-fit* matches the detected ink extents exactly. Untick it to set
     points yourself.
   * **Colour**: sampled from the stroke cores; click to change.
   * **Anchor**: when the new text is a different length, keep it centred, or pinned
     to the left or right edge of the original text.
   * **Inpaint grow**: enlarge the removal mask when glow or shadow remains.
   * ⚠ in the size column means the chosen font lacks some glyphs (e.g. `€`, `ñ`).
4. **Render preview** (⌘R) runs the inpainting and vector text at full 300 dpi.
   Tick **Show rendered result** to see it on the review canvas.
5. **Before / After** tab: a split view at real output resolution. Mouse wheel = zoom,
   drag = pan, drag the white handle = move the split, double-click = 100 %. Modes:
   plain bicubic vs final, upscaled raster vs final, bicubic vs upscaled.
6. **Export PDF + PNG…** (⌘E) writes, into the folder you choose:

| File | Content |
|---|---|
| `<name>_A1.pdf` | A1 page (594 × 841 mm), 300 dpi background (JPEG q95 4:4:4 or lossless), vector text with embedded subset fonts. The text is selectable and searchable. |
| `<name>_A1_300dpi.png` | The same page flattened: 7016 × 9933 px with the 300 dpi tag. The text layer is rendered by the PDF engine, so it matches the PDF exactly. |
| `<name>_report.txt / .json` | Resolution report (below). |
| `<name>.tfe.json` | Your review edits. Re-opening the image, or a batch run, offers to reuse them. |

### The dpi report

* **Native ppi**: source pixels per printed inch. A 1024 px wide image across ~541 mm
  is ≈ 48 ppi.
* **Upscaled ppi**: after Real-ESRGAN 4x (≈ 192 ppi for that example).
* **Effective ppi** = min(upscaled ppi, output dpi). Detail above native is
  *reconstructed* by the network, not captured. The report states this.
* **Minimum viewing distance** at which pixels can no longer be resolved, using
  1 arc-minute acuity (d ≈ 3438 / ppi inches). Example: 48 ppi → 1.8 m,
  192 ppi → 0.45 m.
* Vector text is resolution-independent and is listed per box with font and size.

## Batch mode

**File → Batch folder…** (⌘B), or drop a folder on the window. Every PNG/JPG in the
folder is processed with the current settings and no review step. Vectorised boxes
are chosen as *confident* (OCR confidence ≥ 0.6), *all*, or *none*, and any saved
`.tfe.json` edits are reused. A `batch_summary.csv` is written. From the terminal:

```bash
"/Applications/TFE Poster Maker.app/Contents/MacOS/TFE Poster Maker" batch ~/Posters -o ~/Posters/A1
"/Applications/TFE Poster Maker.app/Contents/MacOS/TFE Poster Maker" process image.png --vectorise all --font "Helvetica Neue Bold"
```

Options: `--orientation`, `--margin MM`, `--no-upscale`, `--model`, `--tile N` (lower
it if the GPU runs out of memory), `--vectorise auto|all|none`, `--font NAME`,
`--lossless`.

## Upscaling models

| Model | Use |
|---|---|
| `realesr-animevideov3` (default) | Conservative illustration/anime model; least hallucination on flat colour, line art and typography. |
| `realesrgan-x4plus-anime` | Stronger anime model; sharper but can flatten texture. |
| `realesrgan-x4plus` | General/photographic images. |

If the source already reaches the target dpi, upscaling is skipped. If the binary is
missing, the app falls back to Lanczos and says so in the report.

## How the text replacement works

* **Detection**: `VNRecognizeTextRequest` (accurate level, language correction; en, es,
  ca where supported), on-device.
* **Colour / mask**: a robust planar fit (a + bx + cy, with iterative outlier
  rejection) models the local background, so text on gradients is separated cleanly.
  An Otsu threshold on the colour distance gives the stroke pixels. The text colour
  is the median of the stroke cores; weight comes from the stroke-width/height ratio.
* **Inpainting**: OpenCV Telea or Navier-Stokes on a local crop at capped
  resolution, composited only inside the (grown, feathered) mask.
* **Placement**: the text's ink box is measured by rendering it with MuPDF, the same
  engine that writes the PDF. Size and position are then solved so the vector ink
  matches the detected ink. On test images, auto size is within 1 % of the true size
  and position within 2 source pixels.

## Development

```bash
pip install -r requirements.txt pytest
pytest -q                                   # 17 tests (layout, PDF/PNG, inpaint, alignment, EXIF, upscaler)
python scripts/make_samples.py samples      # synthetic test posters
QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py samples/portrait_poster.png /tmp/shots
```

Code layout: `tfe_poster/` holds `layout.py` (A1 fit, margin colour), `upscale.py`
(Real-ESRGAN wrapper), `ocr.py` (Vision; Tesseract only for testing off-Mac),
`textstyle.py`, `inpaint.py`, `fonts.py`, `project.py` (pipeline, PDF/PNG export,
report), `batch.py`, `cli.py`, and `gui/` (main window, review, compare).

## Troubleshooting

* **"Real-ESRGAN not found"**: run `scripts/fetch_realesrgan.sh` before building, or
  set `TFE_REALESRGAN=/path/to/realesrgan-ncnn-vulkan`.
* **Real-ESRGAN fails with a memory error**: use `--tile 256` (or 128).
* **OCR finds nothing**: check `doctor` reports *Apple Vision*. Very stylised lettering
  may not be recognised; that text then simply stays raster.
* **Text still faintly visible after vectorising**: raise *Inpaint grow* for that box
  (glows and drop shadows extend beyond the strokes).
* **Fonts**: the app scans `/System/Library/Fonts`, `/Library/Fonts` and
  `~/Library/Fonts`. Install a font there and restart the app to use it.
