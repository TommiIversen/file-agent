# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for File Transfer Agent.

Builds a single-directory macOS app that bundles:
  - The FastAPI/Uvicorn application
  - All Jinja2 templates
  - All static assets (CSS, JS)
  - settings.env (default config)

Usage (on a macOS machine or GitHub Actions macOS runner):
  pip install pyinstaller
  pyinstaller file-agent.spec
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

PROJECT_ROOT = os.path.abspath(".")

# Collect ALL app submodules so uvicorn's dynamic import of "app.main:app" works
app_hiddenimports = collect_submodules("app")

# Collect rich unicode data files (module names with hyphens confuse PyInstaller)
rich_datas = collect_data_files("rich")
rich_hiddenimports = collect_submodules("rich")

# Collect all data files that must ship with the binary
datas = rich_datas + [
    # Jinja2 templates
    (
        os.path.join(PROJECT_ROOT, "app", "domains", "presentation", "templates"),
        os.path.join("app", "domains", "presentation", "templates"),
    ),
    # Static assets (CSS, JS, images)
    (
        os.path.join(PROJECT_ROOT, "app", "domains", "presentation", "static"),
        os.path.join("app", "domains", "presentation", "static"),
    ),
    # Default settings file (user can override with host-specific file)
    (
        os.path.join(PROJECT_ROOT, "settings.env"),
        ".",
    ),
]

# Hidden imports that PyInstaller can't discover via static analysis
hiddenimports = app_hiddenimports + rich_hiddenimports + [
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
    "uvicorn.lifespan.off",
    "httptools",
    "websockets",
    "aiofiles",
    "jinja2",
    "multipart",
    "pydantic",
    "pydantic_settings",
    "rich",
    "httpx",
    "httpx._transports",
    "httpx._transports.default",
]

a = Analysis(
    ["run.py"],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "test",
        "setuptools",
        "pip",
        "wheel",
    ],
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
    name="file-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,       # Headless service — no GUI
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="file-agent",
)
