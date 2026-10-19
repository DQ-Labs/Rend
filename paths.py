"""Where Rend's bundled files live, in a source checkout and in the frozen build.

Every lookup of a shipped file — ffmpeg/ffprobe, rend.ico, assets/, the
vendored demucs — goes through bundle_dir() so the frozen-vs-source decision is
made in exactly one place.

The installer ships a PyInstaller *one-dir* build:

    Rend\\Rend.exe          the launcher (what shortcuts point at)
    Rend\\_internal\\...     python runtime, torch, ffmpeg.exe, assets, demucs

PyInstaller 6 points sys._MEIPASS at that _internal folder (in a one-file build
it pointed at the temp dir the EXE unpacked itself into), so _MEIPASS stays the
right answer either way. Note that the folder holding Rend.exe is *not* where
the bundled files are — anything that joins a name onto
os.path.dirname(sys.executable) will miss them.

Stdlib only: app.py imports this before the splash, and CI imports it bare.
"""

import os
import sys

# PyInstaller 6's default contents directory for one-dir builds.
CONTENTS_DIR = "_internal"


def is_frozen():
    """True when running from a PyInstaller build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir():
    """The directory that holds Rend's bundled files.

    Frozen: sys._MEIPASS (the one-dir build's _internal folder). PyInstaller
    always sets it; the fallbacks only guard against a build made with a
    different contents_directory or a bootloader that doesn't. Source: the
    project root, where the README tells users to drop ffmpeg.exe.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    if is_frozen():
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        internal = os.path.join(exe_dir, CONTENTS_DIR)
        return internal if os.path.isdir(internal) else exe_dir
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative_path):
    """Absolute path of a bundled file, e.g. resource_path("assets/app_icon.png")."""
    return os.path.join(bundle_dir(), relative_path)
