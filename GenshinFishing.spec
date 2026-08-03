# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build: pyinstaller GenshinFishing.spec

One self-contained GenshinFishing.exe. `assets/` is bundled inside it and
read from sys._MEIPASS; setting.ini and genshinfishing.log stay next to the
exe, so the build is portable and the user's config survives a rebuild.

uac_admin embeds a requireAdministrator manifest: Genshin ignores synthetic
input from a non-elevated process, so the exe has to start elevated. Windows
raises the UAC prompt itself, which is why the in-script relaunch never fires
for a packaged build.
"""

a = Analysis(
    ['genshin_fishing.py'],
    pathex=[],
    binaries=[],
    # only the resolutions and reference icons the bot actually reads
    datas=[('assets', 'assets')],
    # both are imported inside functions, where the bytecode scan can miss them
    hiddenimports=['tools.aim_cast', 'tools.fish_scan'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # trims ~40 MB of scientific/GUI baggage that opencv-python drags along
    excludes=['tkinter', 'matplotlib', 'PIL', 'scipy', 'pandas',
              'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython',
              'pytest', 'unittest', 'setuptools', 'pip'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GenshinFishing',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed exes get flagged by Defender far more
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # the bot's log goes to stdout as well as the file
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=None,
)
