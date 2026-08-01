"""Rend's identity: the single source of truth for name, version, and URLs.

Everything that states who this app is — the window title, the splash
screen, the About pane, bug-report links, CI's tag-vs-version check, and
(eventually) the installer — reads from here. Bumping the version or
renaming the app is a one-line change in this file and nowhere else.

Keep this module dependency-free: it is imported before the splash screen,
and CI parses it with a bare `python -c "import config"` with no packages
installed.
"""

APP_NAME = "Rend"
APP_VERSION = "1.3.0"
APP_TAGLINE = "AI Music Stem Separator"
BUNDLE_ID = "com.dqlabs.rend"
AUTHOR = "DQ-Labs"
COPYRIGHT = "Copyright (c) 2026 DQ-Labs. MIT License."

REPO_URL = "https://github.com/DQ-Labs/Rend"
HOMEPAGE = REPO_URL
RELEASES_URL = f"{REPO_URL}/releases"
BUG_REPORT_URL = f"{REPO_URL}/issues/new?template=bug_report.md"

# Load-bearing dependencies shown in the About pane: (name, license, url)
CREDITS = [
    ("Demucs", "MIT — Meta AI Research", "https://github.com/adefossez/demucs"),
    ("Mel-Band RoFormer", "MIT — lucidrains / ZFTurbo", "https://github.com/lucidrains/BS-RoFormer"),
    ("PyTorch", "BSD-3-Clause", "https://pytorch.org"),
    ("CustomTkinter", "MIT", "https://github.com/TomSchimansky/CustomTkinter"),
    ("python-soundfile", "BSD-3-Clause", "https://github.com/bastibe/python-soundfile"),
    ("FFmpeg", "GPL (bundled binary)", "https://ffmpeg.org"),
]
