"""Frozen-path resolution for the one-dir build — headless, no PyInstaller needed.

The frozen cases are simulated by setting sys.frozen / sys._MEIPASS /
sys.executable the way PyInstaller 6's bootloader does for a one-dir build:
_MEIPASS is the _internal folder beside Rend.exe, not the folder holding it.
"""

import importlib.util
import os
import sys

import pytest

import paths
import rend_core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def onedir(tmp_path, monkeypatch):
    """A fake installed one-dir build: <app>/Rend.exe + <app>/_internal/..."""
    app = tmp_path / "Rend"
    internal = app / "_internal"
    (internal / "assets").mkdir(parents=True)
    (app / "Rend.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "Rend.exe"))
    return app, internal


def test_source_checkout_resolves_to_project_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert not paths.is_frozen()
    assert paths.bundle_dir() == ROOT
    assert os.path.isfile(paths.resource_path("rend.ico"))
    assert os.path.isfile(paths.resource_path(os.path.join("assets", "app_icon.png")))


def test_onedir_build_resolves_to_internal_not_exe_dir(onedir):
    app, internal = onedir
    assert paths.is_frozen()
    assert paths.bundle_dir() == str(internal)
    assert paths.bundle_dir() != os.path.dirname(sys.executable)
    assert paths.resource_path("rend.ico") == os.path.join(str(internal), "rend.ico")


def test_frozen_without_meipass_falls_back_to_internal(onedir, monkeypatch):
    app, internal = onedir
    monkeypatch.delattr(sys, "_MEIPASS")
    assert paths.bundle_dir() == str(internal)


def test_frozen_without_internal_folder_falls_back_to_exe_dir(tmp_path, monkeypatch):
    (tmp_path / "Rend.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Rend.exe"))
    assert paths.bundle_dir() == str(tmp_path)


def test_contents_dir_matches_spec_and_installer():
    # paths.py, Rend.spec and the installer's delete entries must all name the
    # same folder, or upgrades/uninstalls leave the real one behind.
    spec = open(os.path.join(ROOT, "Rend.spec"), encoding="utf-8").read()
    iss = open(os.path.join(ROOT, "installer", "Rend.iss"), encoding="utf-8").read()
    assert f"contents_directory='{paths.CONTENTS_DIR}'" in spec
    assert f'Name: "{{app}}\\{paths.CONTENTS_DIR}"' in iss


# ── ffmpeg lookup ─────────────────────────────────────────────────────────────

def _ffmpeg_name():
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def test_ffmpeg_exe_finds_the_copy_in_internal(onedir, monkeypatch):
    app, internal = onedir
    bundled = internal / _ffmpeg_name()
    bundled.write_bytes(b"")
    monkeypatch.setattr(rend_core.shutil, "which", lambda name: None)  # not on PATH
    assert rend_core.ffmpeg_exe() == str(bundled)


def test_ffmpeg_exe_ignores_a_copy_beside_the_exe(onedir, monkeypatch):
    # The one-file layout put ffmpeg next to the code; in one-dir, a stray copy
    # beside Rend.exe is not part of the build and must not be what we find.
    app, internal = onedir
    (app / _ffmpeg_name()).write_bytes(b"")
    monkeypatch.setattr(rend_core.shutil, "which", lambda name: None)
    assert rend_core.ffmpeg_exe() == "ffmpeg"


def test_ffmpeg_exe_prefers_path(onedir, monkeypatch):
    monkeypatch.setattr(rend_core.shutil, "which", lambda name: "/somewhere/ffmpeg")
    assert rend_core.ffmpeg_exe() == "/somewhere/ffmpeg"


def test_path_prepend_makes_bundled_ffmpeg_findable(onedir, monkeypatch):
    # demucs finds ffmpeg through PATH only; app.py prepends bundle_dir().
    # Reproduce that prepend and check shutil.which resolves the bundled copy.
    app, internal = onedir
    exe = internal / _ffmpeg_name()
    exe.write_bytes(b"#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", paths.bundle_dir() + os.pathsep + "")
    import shutil
    found = shutil.which("ffmpeg")
    # normcase: on Windows which() may return the PATHEXT spelling (ffmpeg.EXE)
    assert found and os.path.normcase(found) == os.path.normcase(str(exe))


def test_app_prepends_bundle_dir_to_path():
    # app.py can't be imported headlessly (it opens a splash), so check the
    # source: the PATH prepend must use paths.bundle_dir(), not the exe's
    # folder or a hand-rolled _MEIPASS lookup.
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert 'os.environ["PATH"] = paths.bundle_dir() + os.pathsep' in src
    assert "sys._MEIPASS" not in src


def test_splash_is_collected_on_main_thread_before_app():
    # The v1.3.1 fix (CONTEXT.md constraint 5): the splash's Tcl interpreter is
    # closed and garbage-collected at module level, before App is defined/built.
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    wait = src.index("_splash.wait(_imports_done)")
    delete = src.index("del _splash", wait)
    collect = src.index("gc.collect()", delete)
    assert collect < src.index("class App(")
    assert collect < src.index("app = App()")


# ── Installer build check ─────────────────────────────────────────────────────

def _load_build_installer():
    spec = importlib.util.spec_from_file_location(
        "build_installer", os.path.join(ROOT, "installer", "build_installer.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_installer_reports_an_incomplete_onedir_build(tmp_path):
    bi = _load_build_installer()
    assert set(bi.missing_files(str(tmp_path))) == set(bi.required_files())
    for rel in bi.required_files():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    assert bi.missing_files(str(tmp_path)) == []


def test_installer_ships_the_whole_folder():
    iss = open(os.path.join(ROOT, "installer", "Rend.iss"), encoding="utf-8").read()
    assert 'Source: "..\\dist\\{#AppName}\\*"' in iss
    assert "recursesubdirs" in iss and "createallsubdirs" in iss
    assert "[InstallDelete]" in iss and "[UninstallDelete]" in iss
    # Shortcuts keep pointing at the same file name the one-file build used.
    assert 'Filename: "{app}\\{#AppName}.exe"' in iss
