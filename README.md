# Rend

A simple Windows GUI for AI Music Stem Separation (Demucs) built with CustomTkinter.

## Features
- **Offline CPU Execution**: Uses `demucs` for processing without requiring a GPU or internet connection for inference (after model download).
- **6 Model Options**: Choose from htdemucs, htdemucs_ft, htdemucs_6s, mdx, mdx_extra, and mdx_q — from fast defaults to high-precision options (see Model Selection below).
- **High Quality Mode**: Enable `shifts=2` for better separation quality (runs slower).
- **Karaoke Mode**: Automatic 2-stem output merging non-vocal stems into a single 'Accompaniment' track.
- **WAV Export**: Saves separated stems directly as WAV files using `soundfile`.
- **Dark Mode GUI**: Clean and modern interface powered by `customtkinter`.
- **Threaded Processing**: Keeps the UI responsive during separation.

## Downloads

**Windows users can download the latest standalone executable (no Python required) from the [Releases Page](https://github.com/DQ-Labs/Rend/releases).**

## Model Selection

| Model | Description |
|---|---|
| `htdemucs` | **Default.** Balanced speed and quality. Good starting point. |
| `htdemucs_ft` | Fine-tuned. Slightly better vocals, but ~4x slower. |
| `htdemucs_6s` | Experimental 6-stem split: Drums, Bass, Vocals, Guitar, Piano, Other. |
| `mdx` | Classic model trained on MusDB HQ. Good baseline. |
| `mdx_extra` | High-precision. Uses extra training data. Good for complex mixes. |
| `mdx_q` | Quantized. Smaller download, slightly lower quality. |

## Installation

### Prerequisites
- **Python 3.10+**
- **FFmpeg**: `ffmpeg.exe` and `ffprobe.exe` must be present in the root directory.

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/DQ-Labs/Rend.git
   cd Rend
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. Install direct dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install Demucs and patch for Windows compatibility:
   ```powershell
   .\setup_dev.ps1
   ```
   *This script clones the Demucs source, applies Windows compatibility patches, and installs it as an editable package.*

## Usage

Run the application:
```bash
python app.py
```

1. Click **Select Audio File** and choose an MP3, WAV, or FLAC file.
2. Pick a model and toggle options as desired.
3. Click **SEPARATE STEMS**.

Output stems are saved as WAV files in a folder named `<filename>_stems` next to the input file (e.g. `mysong.mp3` → `mysong_stems/`).

## Architecture
- **Local Demucs Source**: The project relies on a local copy of the `demucs` library in `demucs_source/`, installed via `pip install -e .` with custom compatibility patches applied by `setup_dev.ps1`.
- **Dependency Management**: Core dependencies (`torch`, `soundfile`, `customtkinter`) are listed in `requirements.txt`. Demucs must be installed from source.

## Building from Source

To create a standalone EXE file using PyInstaller:

1. **Prerequisites**:
   - `ffmpeg.exe` and `ffprobe.exe` present in the root directory.
   - Virtual environment activated with all dependencies installed (see Setup above).

2. **Build**:
   ```bash
   pyinstaller Rend.spec --clean --noconfirm
   ```

   The `Rend.spec` file is configured to:
   - Include `demucs_source` in the path and data bundle.
   - Bundle `ffmpeg.exe` and `ffprobe.exe` binaries.
   - Handle hidden imports for `demucs` and `soundfile`.
   - Create a single-file executable (`dist/Rend.exe`).

## Known Behavior
- **Launch Time**: The `.exe` takes approximately **30 seconds to launch**. This is normal for a PyInstaller one-file build as it unpacks to a temporary runtime directory on first launch.
- **First Run**: On the very first separation, the app will automatically download the necessary AI model weights. This requires an internet connection and may take a few minutes. Subsequent runs are fully offline.
- **Windows SmartScreen**: Because the executable is unsigned, Windows may show a SmartScreen warning on first launch. Click "More info" → "Run anyway" to proceed.
