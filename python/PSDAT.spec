# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['psdat_gui', 'scipy.integrate', 'scipy.integrate._ivp', 'studies', 'figstyle', 'cases', 'system', 'units', 'network', 'linearize', 'design', 'simulate', 'facts', 'matplotlib.backends.backend_agg']
hiddenimports += collect_submodules('scipy.optimize')


a = Analysis(
    ['psdat_launch.py'],
    pathex=[],
    binaries=[],
    datas=[('case68_16m.m', '.')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide2', 'PyQt5', 'PySide6', 'PyQt6', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PSDAT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
