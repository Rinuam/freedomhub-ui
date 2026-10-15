#!/usr/bin/env bash
# One-time download of the Real-ESRGAN ncnn/Vulkan macOS build (binary + models)
# into vendor/realesrgan. After this the app runs fully offline.
set -euo pipefail
cd "$(dirname "$0")/.."
URL="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"
DEST="vendor/realesrgan"
if [[ -x "$DEST/realesrgan-ncnn-vulkan" ]]; then
  echo "Already present: $DEST"; exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL"
curl -fL --retry 3 -o "$TMP/esr.zip" "$URL"
mkdir -p "$TMP/x" "$DEST"
unzip -q "$TMP/esr.zip" -d "$TMP/x"
BIN="$(find "$TMP/x" -name realesrgan-ncnn-vulkan -type f | head -1)"
MODELS="$(dirname "$BIN")/models"
cp "$BIN" "$DEST/"
cp -R "$MODELS" "$DEST/"
chmod +x "$DEST/realesrgan-ncnn-vulkan"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
echo "Installed to $DEST:"
ls "$DEST" "$DEST/models"
