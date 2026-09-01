# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

block_cipher = None

a = Analysis(
    [str(SRC / "express" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "express",
        "express.commands",
        "express.config",
        "express.display",
        "express.models",
        "express.repl",
        "express.service",
        "express.storage",
        "express.status",
        "express.validation",
        "express.providers",
        "express.providers.base",
        "express.providers.apizero",
        "express.providers.alapi",
        "express.providers.fallback",
        "express.providers.huawei_jm",
        "express.providers.huawei_kd100",
        "express.providers.ali_kd100",
        "express.providers.mock",
        "express.providers._guess",
        "express.providers._common",
        "httpx",
        "anyio",
        "certifi",
        "rich",
        "rich.console",
        "rich.table",
        "rich.panel",
        "rich.text",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "typer", "click"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="express",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="express",
)
