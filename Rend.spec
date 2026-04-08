# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=['.', 'demucs_source'],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.')],
    datas=[('demucs_source/demucs', 'demucs'), ('rend.ico', '.')],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
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
