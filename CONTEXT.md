# Rend — context for contributors and coding agents

Windows GUI for AI music stem separation. Two engines — Demucs and a vendored
Mel-Band RoFormer — behind one CustomTkinter shell, shipped as a PyInstaller
one-dir build (`Rend.exe` + `_internal/`) inside an Inno Setup installer. Current version: see `config.py`
(the single source of truth; CI refuses a tag that doesn't match it).

The README covers features, install and releasing. This file is the part a
change is most likely to break.

## Layout

| File | Role |
|---|---|
| `config.py` | Identity: name, version, URLs, credits. Dependency-free (CI imports it bare). |
| `paths.py` | `bundle_dir()` / `resource_path()`: the one place that decides where bundled files live (frozen → `sys._MEIPASS` = `_internal`; source → project root). Stdlib only. |
| `registry.py` | Model catalog — engine, stems, karaoke/High Quality applicability, download URL/size/sha256/license. Stdlib only. |
| `downloader.py` | SHA256-verified weight downloads (`.part` → verify → atomic replace), cancellable per block. Stdlib only. |
| `serato_stems.py` | Serato DJ `.serato-stems` reader/writer and export: Serato's length rule, its undelayed decode, MP3 encode + verify. numpy/soundfile only, no torch or GUI. |
| `rend_core.py` | Engines (`DemucsEngine`, `RoformerEngine`), `SeparationThread`, stem saving, output folders, diagnostics. No GUI imports. |
| `roformer_source/` | Vendored Mel-Band RoFormer architecture + chunked inference (MIT lineage in `mel_band_roformer.py`). |
| `app.py` | The CustomTkinter shell, splash screen, license gate. Not importable in CI. |
| `tests/` | Headless tests for everything except `app.py`; CI runs them before any build. |

## Constraints (do not break)

1. **Patched Demucs at a pinned commit.** `setup_dev.ps1` and CI clone
   facebookresearch/demucs at `e976d93` and strip `lameenc`/`torchaudio` from
   its requirements. Never bump it without a full separation test.
2. **Save stems with `soundfile` only** — never TorchAudio or demucs' own save,
   which hang or crash in the windowed build.
3. **The GUI thread never blocks.** Heavy work runs on daemon threads; the UI is
   only touched via `self.after(...)` from the main thread.
4. **Windowed builds have no real stdout/stderr.** `app.py` installs a
   `DummyStream`; demucs runs with `progress=False` so tqdm never probes it.
   Tk callback errors go to `%LOCALAPPDATA%\Rend\error.log`.
5. **The splash owns a second Tcl interpreter and must be destroyed and
   garbage-collected on the main thread** before the app window is built.
   Otherwise a worker thread can free it and Tcl aborts the whole process
   (`Tcl_AsyncDelete: async handler deleted by the wrong thread`).
6. **demucs finds ffmpeg through PATH only**, so `app.py` prepends
   `paths.bundle_dir()` to PATH at startup. In the one-dir build that is the
   `_internal` folder, not the folder holding `Rend.exe`. Rend's own `ffmpeg_exe()` searches more
   places — when fixing a lookup, check whether vendored code does it the same way.
7. **Checkpoints load with `torch.load(..., weights_only=True)`** — they come
   from third-party repos, and a plain load would execute arbitrary pickle code.
8. **Never bundle or rehost model weights.** RoFormer checkpoints are published
   without a license grant (`redistributable=False` in the registry); Rend only
   downloads them on demand from the author's repo, after the license gate.
9. **Offline after first use.** No network calls during separation; only the
   first use of a model downloads its weights.

## Things that look wrong but aren't

- **CPU-only installer.** A CUDA build exceeds GitHub's 2 GiB per-file release
  limit. (The one-dir build no longer unpacks per launch, so that is now the
  only blocker.)
  `select_device()` still uses CUDA on a source install with a CUDA torch.
- **RoFormer needs ~16 GB RAM.** Measured 7.4 GB peak on an 8 GB machine, where
  it pages indefinitely. Demucs is fine in ~2 GB. Documented in the README.
- **The Serato export decodes the MP3 differently from everything else.** Serato
  counts `(audio frames + 1 if Info frame) × 1152` samples and rejects (trashes)
  a stems file of any other length, so the export separates ffmpeg's
  `-flags2 +skip_manual` decode with one silent frame prepended — not
  `separate_audio_file`. Each encoded stem is decoded back *from a file* and
  must be exactly that length before anything is written.
- **Each run writes a fresh `<song>_stems (n)` folder**, by design — re-running
  used to overwrite earlier stems and mix different runs' outputs.
- **`Rend.exe` beside an `_internal` folder.** That is the PyInstaller one-dir
  layout (since 1.5.0). Bundled files are under `_internal`, which is what
  `sys._MEIPASS` points at; never join file names onto
  `os.path.dirname(sys.executable)`. The installer wipes `{app}\_internal`
  before installing so an upgrade can't mix two builds' DLLs.
