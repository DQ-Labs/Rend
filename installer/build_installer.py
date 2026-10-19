"""Compile the Rend installer with Inno Setup.

Reads the app's identity (name, version, publisher, URLs) from config.py —
the single source of truth — and passes it to ISCC as /D preprocessor
defines, so installer/Rend.iss never hardcodes any of it.

Usage (after `pyinstaller Rend.spec` has produced the one-dir build in
dist/Rend/ — Rend.exe plus its _internal folder):

    python installer/build_installer.py

Requires Inno Setup 6.3+ — ISCC.exe on PATH or in the default install
location (`choco install innosetup` or https://jrsoftware.org/isinfo.php).
The installer is written to dist/installer/.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config  # noqa: E402


def find_iscc():
    iscc = shutil.which("ISCC")
    if iscc:
        return iscc
    for program_files in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(program_files)
        if base:
            candidate = os.path.join(base, "Inno Setup 6", "ISCC.exe")
            if os.path.isfile(candidate):
                return candidate
    sys.exit(
        "ISCC.exe not found. Install Inno Setup 6.3+ "
        "(`choco install innosetup` or https://jrsoftware.org/isinfo.php)."
    )


# Files the one-dir build must contain, relative to dist/<AppName>/. Checked
# before compiling so a broken PyInstaller build fails here, with a clear
# message, instead of producing an installer that starts and then can't find
# ffmpeg or its icons.
def required_files(app_name=config.APP_NAME):
    return [
        f"{app_name}.exe",
        os.path.join("_internal", "ffmpeg.exe"),
        os.path.join("_internal", "ffprobe.exe"),
        os.path.join("_internal", "rend.ico"),
        os.path.join("_internal", "assets", "app_icon.png"),
        os.path.join("_internal", "demucs", "remote", "files.txt"),
    ]


def missing_files(dist_dir, app_name=config.APP_NAME):
    """Return the required_files() not present under *dist_dir* (empty if complete)."""
    return [rel for rel in required_files(app_name)
            if not os.path.isfile(os.path.join(dist_dir, rel))]


def main():
    dist_dir = os.path.join(ROOT, "dist", config.APP_NAME)
    if not os.path.isdir(dist_dir):
        sys.exit(f"{dist_dir} not found — run `pyinstaller Rend.spec` first.")
    missing = missing_files(dist_dir)
    if missing:
        sys.exit(f"The PyInstaller build in {dist_dir} is incomplete; missing: "
                 + ", ".join(missing))

    cmd = [
        find_iscc(),
        f"/DAppId={config.BUNDLE_ID}",
        f"/DAppName={config.APP_NAME}",
        f"/DAppVersion={config.APP_VERSION}",
        f"/DAppPublisher={config.AUTHOR}",
        f"/DAppURL={config.HOMEPAGE}",
        f"/DAppSupportURL={config.BUG_REPORT_URL}",
        f"/DAppUpdatesURL={config.RELEASES_URL}",
        os.path.join(ROOT, "installer", "Rend.iss"),
    ]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        sys.exit(rc)

    out = os.path.join(
        ROOT, "dist", "installer", f"{config.APP_NAME}-Setup-{config.APP_VERSION}.exe"
    )
    print(f"Installer written to {out}")


if __name__ == "__main__":
    main()
