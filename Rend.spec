# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=['.', 'demucs_source'],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.')],
    datas=[
        ('demucs_source/demucs', 'demucs'),
        ('rend.ico', '.'),
        ('assets', 'assets'),   # UI icons, loaded at runtime via resource_path()
    ],
    hiddenimports=[
        # ── demucs submodules ─────────────────────────────────────────────────
        # PyInstaller only sees static imports; model classes are loaded via
        # torch.load() at runtime so every architecture must be listed here.
        'demucs',
        'demucs.api',
        'demucs.apply',
        'demucs.audio',
        'demucs.pretrained',
        'demucs.repo',
        'demucs.states',       # model weight loader — loads class by name at runtime
        'demucs.utils',
        # Model architecture classes (resolved dynamically from saved checkpoints)
        'demucs.htdemucs',     # HTDemucs  — htdemucs / htdemucs_ft / htdemucs_6s
        'demucs.hdemucs',      # HDemucs   — parent class used by htdemucs family
        'demucs.demucs',       # Demucs    — classic model used by mdx / mdx_extra / mdx_q
        'demucs.transformer',  # transformer blocks used inside HTDemucs
        'demucs.spec',         # spectral utilities used by hdemucs / htdemucs
        'demucs.repitch',      # pitch-shift augmentation referenced in apply.py

        # ── third-party inference dependencies ───────────────────────────────
        # These are imported inside demucs at runtime; PyInstaller's static
        # analysis misses them because they live behind conditional or deep imports.
        'einops',                   # tensor rearrangement — transformer.py
        'julius',                   # audio resampling — apply.py, audio.py
        'openunmix',                # Wiener filtering base package
        'openunmix.filtering',      # explicitly imported in hdemucs.py / htdemucs.py
        'dora',                     # model-loading infrastructure used by repo.py
        'dora.log',
        'dora.utils',
        'omegaconf',                # config management pulled in by dora
        'tqdm',                     # progress bars
        'yaml',                     # pyyaml — imported as 'yaml' in pretrained.py

        # ── numpy / sklearn internals ────────────────────────────────────────
        'numpy',
        'numpy.core.multiarray',
        'numpy.random.common',
        'sklearn.utils._typedefs',

        # ── audio I/O ────────────────────────────────────────────────────────
        'soundfile',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# One-dir build: dist/Rend/Rend.exe plus dist/Rend/_internal/ holding the
# Python runtime, torch, ffmpeg/ffprobe, assets and the vendored demucs.
#
# The one-file build unpacked that whole ~230 MB payload to %TEMP% on every
# launch, which was most of the ~30 s startup and ruled out a CUDA build. The
# installer ships the whole folder, so users still see a single Start-menu
# entry. Runtime code finds bundled files through paths.bundle_dir(), which is
# sys._MEIPASS — the _internal folder in a PyInstaller 6 one-dir build.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # binaries and datas go into COLLECT, not the EXE
    name='Rend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX disabled: compressing the bundled torch/ffmpeg DLLs is a common
    # source of antivirus false positives and occasional broken DLLs
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='rend.ico',
    # PyInstaller 6's default, stated so paths.CONTENTS_DIR and the installer's
    # [InstallDelete]/[UninstallDelete] entries can't silently drift from it.
    contents_directory='_internal',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Rend',
)
