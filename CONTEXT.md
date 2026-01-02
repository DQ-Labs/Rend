# Project: Rend (Music Separation App)
## Current State
- Functional Windows GUI using `customtkinter`.
- Core Logic: Uses `demucs` (installed from source in `demucs_source`).
- Audio Saving: Uses `soundfile` library (NOT `torchaudio` or `demucs.api.save_audio`) to avoid dependencies.
- Hardware: CPU execution only (`device='cpu'`) for compatibility.
- Dependencies: `ffmpeg.exe` and `ffprobe.exe` are present in the root.

## Critical Constraints (DO NOT BREAK)
1. **Do not update Demucs:** We are using a patched version where `lameenc` and `torchaudio` requirements were removed.
2. **Do not use TorchCodec:** It crashes on this environment. Always use `soundfile` to save audio.
3. **Keep it Threaded:** The GUI must remain responsive during the separation process.
4. **Offline First:** The `htdemucs` model is downloaded, but we prefer not to require constant internet access.

## Goals for Improvement
- Improve the GUI styling.
- Add error handling.
- Prepare for PyInstaller packaging (include ffmpeg binaries).