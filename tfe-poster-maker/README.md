# TFE Poster Maker 2

Turn AI-generated images (ChatGPT, Midjourney, Firefly…) into **print-ready posters
(A0–A6, US, custom)** and **social-media images**. The app:

* enhances the image with state-of-the-art AI super-resolution, **up to 16×**;
* replaces the image's text with **real, editable vector text**;
* exports **PDF** (vector text over a high-resolution background) plus **PNG, JPEG, TIFF
  and WebP**.

It is a native macOS app for Apple Silicon (PySide6 + PyTorch on the Apple GPU), and
everything runs **offline** on your Mac.

```
image ─► OCR (Apple Vision) ─► editable text blocks ─┐
      └► AI enhance ×2…×16 (DRCT-L / HAT-L / DAT2 …) │  disk-cached
             + optional JPEG clean-up, face restore  │
                                                     ▼
  LaMa removes the original text on the source ─► cleaned areas re-enhanced with the
  same model (seamless) ─► per output: resample · tone/detail · soft shadows · vector text
                                                     ▼
       A1/A2/A4… PDF (searchable, vector)  ·  Instagram/LinkedIn/YouTube/4K PNG/JPEG/WebP
```

## What's new in 2.0

| Area | v1 | v2 |
|---|---|---|
| Enhancement | Real-ESRGAN 4× | **DRCT-L, HAT-L, DAT2, ATD, SwinIR-L, RealPLKSR, RCAN, ESRGAN**, up to **16×** (multi-pass), model blending, ×8 TTA, auto model choice |
| Restoration | – | FBCNN JPEG clean-up, SCUNet denoise, GFPGAN / CodeFormer faces |
| Tone & detail | – | exposure, contrast, highlights, shadows, saturation, vibrance, warmth, tint, clarity, sharpen, denoise, grain (live preview) |
| Text removal | OpenCV | **LaMa** (big-lama), then the region is re-enhanced and tone-matched |
| Text | font, size, colour | HarfBuzz shaping (kerning, ligatures), **multi-line**, tracking, line height, alignment, case, outline, hard and soft shadow, opacity, rotation, synthetic bold/italic, drag-to-move, add or delete text, **font matching** |
| Outputs | A1 PDF + PNG | A0–A6, B1/B2, US sizes, posters, custom mm at 150–600 dpi with bleed; 14 social presets plus custom px; original aspect up to 16384 px; **PDF / PNG / JPEG / TIFF / WebP**, sRGB-tagged |

## Install

### Option A: build the app on your Mac (recommended, one time)

Requirements: Apple Silicon Mac, macOS 13+, Python 3.11–3.13 (from python.org or
`brew install python@3.12`), about 8 GB of free disk.

```bash
git clone -b claude/install-ui-ux-pro-max-k9vxvj https://github.com/rinuam/freedomhub-ui.git
cd freedomhub-ui/tfe-poster-maker
scripts/build_app.sh --dmg         # ≈15–30 min; downloads PyTorch + ~1.2 GB of models once
open dist                          # drag "TFE Poster Maker.app" to Applications
```

* `--no-models` builds a smaller app; you then download models inside the app (**Models…**).
* `--all-models` bundles every model in the catalogue (~2.5 GB).
* The first launch needs a right-click → **Open**, because the app is ad-hoc signed and not
  notarised.
* The build ends with a self-check (`doctor`). It should report
  `PyTorch … on mps` and `OCR: Apple Vision`.

### Option B: run from source

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mac.txt
scripts/fetch_models.sh            # recommended models into vendor/models
python -m tfe_poster               # GUI
python -m tfe_poster doctor
```

## Using the app

The window has three areas: **Enhance** on the left, the **Editor / Before-After / Report**
tabs in the centre, and **Text** and **Outputs** on the right.

1. **Open** an image (⌘O), or drop it on the window. Text is detected immediately.
2. **Text** tab: every detected line is listed. Ticked lines become vector text.
   * Click a line, or click it on the canvas, to edit it. You can change the text
     (multi-line), family and style, size (shown in **pt on your print size**), tracking,
     line height, alignment, case, kerning and ligatures, extra bold and slant, fill colour
     and opacity, outline, shadow (offset and softness), position and rotation.
   * **Fit to original** sizes the text exactly over the detected lettering.
     **Suggest matching fonts…** compares the original lettering against every installed
     font and ranks them.
   * **＋ Text** adds new text (click where it should go). **Merge** joins selected lines
     into one paragraph. **Duplicate** and **Delete** do what they say. **Apply this style
     to…** copies a style to the other blocks.
   * Drag text on the canvas to move it; the arrow keys nudge it (Shift = 10 px).
   * **⌫ Erase area**: drag a rectangle to remove anything (logos, artefacts, watermarks).
   * A detected line can also be erased without replacing it: tick *Erase original* and
     untick *Vector text*.
3. **Enhance** panel:
   * **Preset**:
     * **Auto** analyses the image. Clean PNGs get **DRCT-L**; JPEG/WebP-blocky images
       get **FBCNN clean-up + HAT-L**.
     * The other presets are DRCT-L, HAT-L, DAT2, DRCT-L + HAT-L detail blend,
       AnimeSharp and Fast.
   * **Enlarge**: *Auto* picks the smallest power of two that covers your largest output
     (e.g. A1 @ 300 dpi from 1024×1536 → 8×). You can also choose 2, 4, 8 or 16×. Every
     step is an AI pass, never plain interpolation.
   * **Detail model + blend** mixes a second model into each tile (e.g. 35 % HAT-L for
     micro-texture). **TTA ×8** averages 8 flipped/rotated runs: slightly cleaner, 8× slower.
   * **Pre-clean**: FBCNN (JPEG artefacts) or SCUNet (noise), at source resolution.
     **Faces**: GFPGAN 1.4 (or CodeFormer; see licences).
   * **Tone and detail** sliders update the preview live (double-click a slider to reset).
   * **Test on visible area** runs the current settings on a 256 px crop of what you see,
     for quick model comparison.
   * **✨ Enhance with AI** (⌘R) shows a rough time estimate first. Results are cached, so
     re-opening the image or changing text never repeats the AI run.
4. **Show:** switches the canvas between *Original*, *AI enhanced* and *Final background*
   (text removed; this is what the PDF uses under the vector text).
5. **Before / After** tab: a zoomable split view (up to 200 %) of original vs AI vs final.
6. **Outputs** tab: tick the outputs you want, or **＋ Add output**. For each one you can
   set:
   * **Print**: paper, orientation, dpi (150–600), margin and bleed (the PDF trim box is set).
   * **Social / screen**: Instagram 1:1, 4:5 and story, Facebook, LinkedIn, X, YouTube,
     Pinterest, Full HD, 4K, 8K or custom pixels.
   * **Framing**: *Fit* (colour margins: edge-sampled, white, black or `#rrggbb`),
     *Extend* (blurred-image background, ideal for social sizes) or *Fill* (crop, with a
     focus point).
   * **Formats**: PDF, PNG, JPEG, TIFF, WebP, plus quality and PDF background encoding.
   * **⬇ Export** (⌘E) writes every checked output, a quality report, and
     `<name>.tfe.json` (your edits, re-loadable).
7. **Batch…** (⌘B) processes a folder with the current Enhance settings and the checked
   outputs. Saved edits are reused.

## Models

Open **Models…** to see every model with its size, speed, licence and status. You can
download (SHA-256 verified), delete, or **import any spandrel-compatible model** (most of
openmodeldb.info).

| Model | Best for | Speed | Licence |
|---|---|---|---|
| DRCT-L Nomos2 HQ | clean AI art: sharpest, no invented texture | slow | CC-BY-4.0 |
| HAT-L Nomos8k OTF | photos, blur, noise, compression; generates detail | slowest | CC-BY-4.0 |
| DAT2 RealWebPhoto v4 | JPEG/WebP downloads, screenshots | medium | CC-BY-4.0 |
| ATD Nomos2 HQ | alternative to DRCT-L | slow | CC-BY-4.0 |
| DAT Nomos8k, SwinIR-L | photo GAN alternatives | medium | CC-BY-4.0 / Apache-2.0 |
| RealPLKSR Nomos2 / WebPhoto | fast, very good drafts and batches | fast | CC-BY-4.0 |
| AnimeSharp V4 RCAN (2×) | anime and flat colour | medium | **CC-BY-NC-SA** |
| Real-ESRGAN x4plus / anime / x2 / general v3 | classic | fast | BSD-3 |
| FBCNN, SCUNet | JPEG clean-up, denoise | medium | Apache-2.0 |
| GFPGAN 1.4 | faces | – | Apache-2.0 |
| CodeFormer | faces | – | **non-commercial** |
| LaMa | text removal | – | Apache-2.0 |

⚠ For company deliverables, avoid the **non-commercial** models (CodeFormer, AnimeSharp
V4). The recommended bundle contains only commercially usable models.

**Speed** (Apple GPU, 1024×1536 source, very rough): RealPLKSR 4× ≈ 10–20 s,
DAT2 ≈ 1–2 min, DRCT-L / HAT-L ≈ 3–8 min. A 16× second pass takes about 16× longer.
Use *Test on visible area* to judge a model before a long run.

## Command line

```bash
APP="/Applications/TFE Poster Maker.app/Contents/MacOS/TFE Poster Maker"
"$APP" doctor
"$APP" models                                   # list; --download default|all|<ids>
"$APP" process poster.png --print A1 --print A3 --social "Instagram portrait 4:5" \
       --preset "Best · real" --factor 8 --faces gfpgan-1.4 --sharpen 0.3 -o out/
"$APP" batch ~/Posters --print A2 --social "LinkedIn post" --vectorise all --font "Helvetica Neue Bold"
```

## Quality notes

* The text is real vector outlines, razor sharp at any size, plus an invisible text layer
  so the PDF stays searchable. The outlines come from the same engine as the editor, so
  what you see is what prints.
* The report gives, for every output, the *native ppi* (real source pixels), the
  *effective ppi* after AI, and the viewing distance beyond which pixels can't be
  resolved. AI adds plausible detail; it cannot recover detail that never existed.
* Text removal runs on the source image (where LaMa works best). The cleaned area is then
  upscaled with the same model and tone-matched to its surroundings, so it is invisible
  after enlargement.

## Troubleshooting

* **"Model not installed"**: open **Models…** and click *Download recommended set*.
* **Out of GPU memory** on huge factors: lower *Tile size* (e.g. 256) or use FP16.
* **OCR missed some text**: add it with **＋ Text**, and remove the original with
  **⌫ Erase area**.
* **Glow around replaced text**: raise *Erase grow* for that block, or drag an erase area
  over the glow.
* **Fonts**: install fonts into `~/Library/Fonts` and restart the app.

## Development

```bash
pip install -r requirements.txt pytest
pytest -q                                      # model tests auto-skip if models are absent
TFE_MODELS=vendor/models pytest -q             # include AI-model tests
QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py samples/portrait_poster.png /tmp/shots
```

Layout of `tfe_poster/`:

* `enhance/`: model catalogue, spandrel/MPS tiled inference, the enhancement pipeline,
  faces, tone/detail adjustments.
* `text/`: block model, HarfBuzz + fontTools engine, PDF/Qt renderers, font matching.
* `formats.py`: paper, social and placement geometry.
* `project.py`: OCR → enhance → clean → render → export.
* `inpaint.py`: LaMa/OpenCV text removal.
* `gui/`: the app.
