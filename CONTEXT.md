# Project: Rend (Music Separation App)

## Current State (v0.9)

**Status**: Feature-complete. Working toward v1.0 final release with hygiene polish.

- Fully functional Windows GUI using CustomTkinter (dark mode, responsive threading)
- Animated math-curve (Rose Orbit) splash screen during startup
- 6 Demucs model options (htdemucs, htdemucs_ft, htdemucs_6s, mdx, mdx_extra, mdx_q)
- Karaoke mode (2-stem output: vocals + accompaniment)
- High quality mode (shifts=2 for slower but higher-precision separation)
- Cancel button to abort processing at segment boundaries
- Open output folder directly from completion dialog
- Real-time status lights (FFmpeg, Online connectivity)
- WAV export via soundfile (no TorchAudio/lameenc dependencies)
- CPU-only execution for universal Windows compatibility
- PyInstaller one-file EXE with bundled FFmpeg and Demucs source
- MIT licensed

## Critical Constraints (DO NOT BREAK)

1. **Patched Demucs**: Using fork at commit e976d93 with `lameenc` and `torchaudio` requirements removed. Never update without testing.
2. **Audio Export**: Always use `soundfile` to save WAV. Never use TorchAudio or internal Demucs save (causes hangs/crashes).
3. **Threading**: GUI must stay responsive during separation. All heavy work on daemon threads with `self.after()` for UI updates.
4. **No DummyStream Methods**: `DummyStream` (for `--noconsole` mode) lacks `isatty()`. Must set `progress=False` on Separator to avoid tqdm calling it.
5. **Offline Execution**: After first model download, app works fully offline. No API calls during separation.

## Resolved in v0.7–v0.9

✅ **v0.7 (Criticals 1–3)**
- Animated splash during import phase
- Dynamic error handling in splash load
- Model description legibility and UI polish
- Bottom clipping fixed (720px window)
- Attribution text restored

✅ **v0.7.2 (Criticals 4–5 + License)**
- `progress=False` fix (tqdm + DummyStream incompatibility)
- Karaoke guard for htdemucs_6s (different stem names)
- MIT License + Demucs attribution

✅ **v0.8 (Must-Haves)**
- WM_DELETE_WINDOW crash fixed (confirmation dialog)
- Progress bar freeze fixed (use `segment_offset` key)
- FFmpeg tooltip/diagnostic dialog
- README button label updated
- Pre-flight diagnostics (FFmpeg, Online status)

✅ **v0.9 (Nice-to-Haves)**
- Cancel button with threading.Event
- Open output folder from completion dialog
- Dead code cleanup (splash.png, generate_splash.py)
- File zone reset after successful run
- CI double-trigger fixed (release:[published] only)
- README rewrite (current features, no outdated screenshots)

## Goals for v1.0

- ✅ All features complete and tested
- ⚙️ Hygiene pass (README, CONTEXT.md, CI, documentation)
- 🎯 Final testing and validation
- 📦 Release to GitHub

## Architecture Notes

- **Splash Screen**: tkinter Tk window with Canvas animation (Rose Orbit curve, 72 particles, ~60fps) on main thread. Blocks until daemon thread finishes imports.
- **Separation Thread**: `SeparationThread(threading.Thread)` wraps Demucs API. Checks `_stop_event` in `handle_progress` callback; raises `KeyboardInterrupt` to abort cleanly.
- **UI Palette**: Dark theme with named color constants (`_WIN_BG`, `_ACCENT`, `_TXT_MID`, etc.) for easy tweaking.
- **PyInstaller**: Spec file bundles FFmpeg, Demucs source in `demucs/` subdir, comprehensive `hiddenimports` for all Demucs modules and transitive deps.
- **Resource Paths**: `resource_path()` handles both dev (current dir) and PyInstaller (`sys._MEIPASS`) modes.

## Testing Checklist for v1.0

- [ ] All 6 models separate correctly
- [ ] Karaoke mode works (2 stems, no vocals KeyError)
- [ ] High quality mode (shifts=2) completes without mdx_extra crash
- [ ] Cancel button stops processing cleanly
- [ ] Open folder dialog works on Windows
- [ ] FFmpeg status light reflects actual availability
- [ ] First-run model download doesn't hang
- [ ] File zone resets after successful separation
- [ ] EXE launches in ~30s, subsequent launches faster
- [ ] No SmartScreen warning (unsigned, but expected)
