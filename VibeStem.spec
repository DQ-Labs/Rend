# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=['.', 'demucs_source'],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.')],
    datas=[('demucs_source/demucs', 'demucs')],
    hiddenimports=['demucs', 'demucs.api', 'demucs.htdemucs', 'demucs.apply', 'demucs.audio', 'demucs.pretrained', 'demucs.repo', 'soundfile', 'sklearn.utils._typedefs'],
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
    a.binaries,
    a.datas,
    [],
    name='VibeStem',
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
