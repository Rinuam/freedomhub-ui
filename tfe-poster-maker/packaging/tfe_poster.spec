# PyInstaller spec for TFE Poster Maker (macOS, Apple Silicon).
# Build with: scripts/build_app.sh
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
ESR = ROOT / "vendor" / "realesrgan"
ICNS = ROOT / "build" / "icon" / "TFE.icns"

datas = [(str(ROOT / "tfe_poster" / "resources"), "tfe_poster/resources")]
if ESR.is_dir():
    datas.append((str(ESR), "realesrgan"))
else:
    print("WARNING: vendor/realesrgan missing - the app will fall back to Lanczos. "
          "Run scripts/fetch_realesrgan.sh first.")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["Vision", "Foundation", "Quartz", "objc", "fontTools.ttLib.tables._g_l_y_f",
                   "tfe_poster.gui.app", "tfe_poster.gui.main_window"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "matplotlib",
              "scipy", "pandas", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TFE Poster Maker",
          console=False, target_arch="arm64", codesign_identity=None,
          entitlements_file=None, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TFE Poster Maker")
app = BUNDLE(
    coll,
    name="TFE Poster Maker.app",
    icon=str(ICNS) if ICNS.is_file() else None,
    bundle_identifier="es.ideaded.tfepostermaker",
    version="1.0.0",
    info_plist={
        "CFBundleName": "TFE Poster Maker",
        "CFBundleDisplayName": "TFE Poster Maker",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSHumanReadableCopyright": "Ideaded SL, Barcelona",
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Image",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["public.png", "public.jpeg"],
        }],
    },
)
