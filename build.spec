"""PyInstaller spec for Zepp PC Manager."""

import os
import sys
from pathlib import Path

# PyInstaller exec() doesn't provide __file__ on all platforms
project_root = Path(os.getcwd())

# Use ZEPP_PC_CONSOLE=0 to hide console window (release mode)
show_console = os.environ.get("ZEPP_PC_CONSOLE", "0") != "0"

_is_win = sys.platform == "win32"
_is_mac = sys.platform == "darwin"

# Base hidden imports for all platforms
_hidden = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "bleak",
    "bleak.backends",
    "bleak.backends.bluezdbus",
    "webview",
    "webview.platforms",
    "webview.platforms.qt",
]

if _is_win:
    _hidden += [
        "bleak.backends.winrt",
        "webview.platforms.mswebview2",
        "webview.platforms.winforms",
    ]
elif _is_mac:
    _hidden += [
        "bleak.backends.corebluetooth",
    ]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[],
    binaries=[],
    datas=[
        (str(project_root / "src" / "server" / "static"), "src/server/static"),
    ],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "scipy", "numpy",
        "PyQt5", "PySide6", "PySide2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="zepp-pc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=show_console,  # Set ZEPP_PC_CONSOLE=1 to show console for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
