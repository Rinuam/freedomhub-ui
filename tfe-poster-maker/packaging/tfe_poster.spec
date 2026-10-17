# PyInstaller spec for TFE Poster Maker 2 (macOS, Apple Silicon). Build with scripts/build_app.sh
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
ESR = ROOT / "vendor" / "realesrgan"
MODELS = ROOT / "vendor" / "models"
ICNS = ROOT / "build" / "icon" / "TFE.icns"

datas = [(str(ROOT / "tfe_poster" / "resources"), "tfe_poster/resources")]
binaries, hidden = [], []
for pkg in ("spandrel", "spandrel_extra_arches", "torchvision", "uharfbuzz", "safetensors"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
if ESR.is_dir():
    datas.append((str(ESR), "realesrgan"))
if MODELS.is_dir() and any(MODELS.iterdir()):
    datas.append((str(MODELS), "models"))
else:
    print("NOTE: vendor/models is empty - models will be downloaded from the app's Models dialog.")

hidden += ["Vision", "Foundation", "Quartz", "objc", "tfe_poster.gui.app", "tfe_poster.gui.main_window"]
hidden += collect_submodules("tfe_poster")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "matplotlib",
              "scipy", "pandas", "torchaudio", "tensorboard", "triton", "tensorflow",
              "onnxruntime", "onnx", "jax", "IPython", "notebook", "sympy.testing"],
    noarchive=False,
    # torch.jit.script (used by spandrel/torchvision) needs the .py sources at runtime
    module_collection_mode={"spandrel": "pyz+py", "spandrel_extra_arches": "pyz+py",
                            "torchvision": "pyz+py", "tfe_poster": "pyz+py"},
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TFE Poster Maker",
          console=False, target_arch="arm64", codesign_identity=None, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TFE Poster Maker")
app = BUNDLE(
    coll,
    name="TFE Poster Maker.app",
    icon=str(ICNS) if ICNS.is_file() else None,
    bundle_identifier="es.ideaded.tfepostermaker",
    version="2.0.0",
    info_plist={
        "CFBundleName": "TFE Poster Maker",
        "CFBundleDisplayName": "TFE Poster Maker",
        "CFBundleShortVersionString": "2.0.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSHumanReadableCopyright": "Ideaded SL, Barcelona",
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["public.png", "public.jpeg", "org.webmproject.webp", "public.tiff"],
        }],
    },
)
