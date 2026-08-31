# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
SRC = ROOT / "src"

a = Analysis(
    [str(SRC / "express" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "express", "express.commands", "express.config", "express.display",
        "express.models", "express.repl", "express.service", "express.storage",
        "express.status", "express.validation",
        "express.providers", "express.providers.base", "express.providers.apizero",
        "express.providers.alapi", "express.providers.fallback",
        "express.providers.huawei_jm", "express.providers.huawei_kd100",
        "express.providers.mock", "express.providers._guess", "express.providers._common",
        "httpx", "anyio", "certifi",
        "rich", "rich.console", "rich.table", "rich.panel", "rich.text",
        "pyreadline3",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "win_runtime_hook.py")],
    excludes=["tkinter", "_tkinter", "typer", "click"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

icon_path = SPEC_DIR / "AppIcon.ico"
icon_arg = str(icon_path) if icon_path.exists() else None

# One-file console EXE: double-click opens a terminal and runs the `express >` REPL.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Express",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=icon_arg,
)
