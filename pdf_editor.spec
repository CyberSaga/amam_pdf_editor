# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the desktop app (one-folder, windowed).
#
# Build (from any directory; paths below resolve against this file):
#   python -m PyInstaller --noconfirm --distpath <out>/dist --workpath <out>/work pdf_editor.spec
# Verified with PyInstaller 6.22.3; the version is not pinned in any requirements file.
# Run:  <out>/dist/pdf_editor/pdf_editor.exe
#
# Frozen children: sys.executable is the app exe, so the render worker, the print helper and the
# recent-file probe are this same exe re-run with --render-worker / --print-helper /
# --recent-probe (main.py dispatches them before any Qt import; argv comes from
# src/render_worker/launch.py). They are imported only by that
# dispatch and by string-named lazy imports, so PyInstaller cannot see them: hidden imports below.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)

hiddenimports = ['src.render_worker.worker_main', 'src.printing.helper_main', 'utils.recent_file_worker',
                 'fitz', 'pymupdf']
for package in ('src.render_worker', 'src.printing', 'controller', 'model', 'view', 'utils'):
    hiddenimports += collect_submodules(package)

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'view' / 'resources'), 'view/resources')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pdf_editor',
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
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='pdf_editor',
)
