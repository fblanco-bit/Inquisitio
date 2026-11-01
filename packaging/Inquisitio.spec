from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files


project_root = Path(SPECPATH).parent
datas = [
    (str(project_root / "assets" / "CT_Practice_Book_2026.pdf"), "assets"),
    (str(project_root / "web"), "web"),
    (str(project_root / "data" / "forms_cache.json"), "data"),
]
for package in ("docx", "pdfminer", "pdfplumber"):
    datas.extend(collect_data_files(package))

a = Analysis(
    [str(project_root / "start_inquisitio.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Inquisitio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Inquisitio",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Inquisitio.app",
        icon=None,
        bundle_identifier="com.inquisitio.desktop",
        info_plist={
            "CFBundleDisplayName": "Inquisitio",
            "CFBundleName": "Inquisitio",
            "CFBundleShortVersionString": "0.5.0",
            "CFBundleVersion": "0.5.0",
            "NSHighResolutionCapable": True,
        },
    )
