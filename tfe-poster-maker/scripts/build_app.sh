#!/usr/bin/env bash
# Build "TFE Poster Maker.app" (Apple Silicon) with PyInstaller.
#   scripts/build_app.sh            -> dist/TFE Poster Maker.app
#   scripts/build_app.sh --dmg      -> also dist/TFE-Poster-Maker.dmg
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == "Darwin" ]] || { echo "Build on macOS"; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || echo "WARNING: not running on arm64; the bundle targets arm64."

PY="${PYTHON:-python3}"
if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip wheel >/dev/null
python -m pip install -r requirements-mac.txt pyinstaller

scripts/fetch_realesrgan.sh

python scripts/make_icon.py build/icon
iconutil -c icns build/icon/TFE.iconset -o build/icon/TFE.icns

rm -rf "build/TFE Poster Maker" "dist/TFE Poster Maker" "dist/TFE Poster Maker.app"
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/tfe_poster.spec

APP="dist/TFE Poster Maker.app"
# Ad-hoc signature so Gatekeeper/AMFI accept the nested binaries on Apple Silicon.
codesign --force --deep --sign - "$APP"
"$APP/Contents/MacOS/TFE Poster Maker" doctor || true

if [[ "${1:-}" == "--dmg" ]]; then
  hdiutil create -volname "TFE Poster Maker" -srcfolder "$APP" -ov -format UDZO dist/TFE-Poster-Maker.dmg
fi
echo "Built: $APP"
