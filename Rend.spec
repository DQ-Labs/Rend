# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=['.', 'demucs_source'],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.')],
    datas=[('demucs_source/demucs', 'demucs'), ('rend.ico', '.')],
    hiddenimports=['demucs', 'demucs.api', 'demucs.htdemucs', 'demucs.apply', 'demucs.audio', 'demucs.pretrained', 'demucs.repo', 'soundfile', 'sklearn.utils._typedefs', 'numpy', 'numpy.core.multiarray', 'numpy.random.common'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='Rend',
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
    icon='rend.ico',
)
