#!/usr/bin/env bash
# Build "TFE Poster Maker.app" (Apple Silicon) with PyInstaller.
#   scripts/build_app.sh                 app + recommended AI models bundled (~3 GB app)
#   scripts/build_app.sh --no-models     smaller app; download models later in the app (Models…)
#   scripts/build_app.sh --all-models    bundle every catalogue model
#   add --dmg to also create dist/TFE-Poster-Maker.dmg
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == "Darwin" ]] || { echo "Build on macOS"; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || echo "WARNING: not on arm64; the bundle targets Apple Silicon."
MODELS=default; DMG=0
for a in "$@"; do
  case "$a" in
    --no-models) MODELS=none ;;
    --all-models) MODELS=all ;;
    --dmg) DMG=1 ;;
  esac
done
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,13), "use Python 3.10-3.13"'
[[ -d .venv ]] || "$PY" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel >/dev/null
python -m pip install -r requirements-mac.txt pyinstaller

scripts/fetch_realesrgan.sh || echo "(Real-ESRGAN ncnn fallback not fetched - optional)"
if [[ "$MODELS" != none ]]; then
  scripts/fetch_models.sh "$MODELS"
fi
python scripts/make_icon.py build/icon
iconutil -c icns build/icon/TFE.iconset -o build/icon/TFE.icns

rm -rf "build/TFE Poster Maker" "dist/TFE Poster Maker" "dist/TFE Poster Maker.app"
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/tfe_poster.spec
APP="dist/TFE Poster Maker.app"
codesign --force --deep --sign - "$APP"
"$APP/Contents/MacOS/TFE Poster Maker" doctor || true
if [[ "$DMG" == 1 ]]; then
  hdiutil create -volname "TFE Poster Maker" -srcfolder "$APP" -ov -format UDZO dist/TFE-Poster-Maker.dmg
fi
echo "Built: $APP"
