# Rend

A simple Windows GUI for AI Music Stem Separation (Demucs) built with CustomTkinter.

## Features
- **Offline CPU Execution**: Uses `demucs` (htdemucs) for processing without requiring a GPU or internet connection for inference (after model download).
- **Model Selection**: Choose between `htdemucs` (Default) and `mdx` (Extra) models.
- **High Quality Mode**: Enable `shifts=2` for better separation quality (processed slightly slower).
- **Karaoke Mode**: Automatic 2-stem output merging stems into 'Vocals' vs 'Backing'.
- **WAV Export**: Saves separated stems directly as WAV files using `soundfile`.
- **Dark Mode GUI**: Clean and modern interface powered by `customtkinter`.
- **Threaded Processing**: Keeps the UI responsive during separation.

## Downloads

**Windows users can download the latest standalone executable (no Python required) from the [Releases Page](https://github.com/DQ-Labs/Rend/releases).**

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

3. Install dependencies using the automated setup script:
   ```powershell
   .\setup_dev.ps1
   ```
   *This script patches the local Demucs copy for Windows compatibility and installs all requirements.*

## Usage

Run the application:
```bash
python app.py
```
- Select an input audio file.
- The stems will be saved in the output directory (default: `separated/` or similar relative path).

## Architecture
- **Local Demucs Source**: The project relies on a local copy of the `demucs` library located in the `demucs_source` folder. This requires an editable install (`pip install -e .`) to function correctly with custom modifications.
- **Dependency Management**: Critical dependencies like `torch` and `soundfile` must be compatible with the system Python version (Python 3.11/3.12 recommended).

## Building from Source

To create a standalone EXE file using PyInstaller:

1. **Requirements**: 
   - Ensure `ffmpeg.exe` and `ffprobe.exe` are in the root directory.
   - Activate your virtual environment.

2. **Build Command**:
   Run the following command to build the executable using the pre-configured spec file:
   ```bash
   pyinstaller Rend.spec --clean --noconfirm
   ```

   **Make sure to run this via your virtual environment's Python** (e.g., `.\venv\Scripts\python.exe -m PyInstaller ...`) if you have multiple Python versions installed.

   The `Rend.spec` file is configured to:
   - Include `demucs_source` in the path and data bundle.
   - Bundle `ffmpeg.exe` and `ffprobe.exe` binaries.
   - Handle hidden imports for `demucs` and `soundfile`.
   - Create a single-file executable (`dist/Rend.exe`).

## Known Behavior
- **Launch Time**: The final `.exe` takes approximately **30 seconds to launch**. This is normal behavior for a PyInstaller "one-file" build as it unpacks temporary files to a runtime directory.
- **First Run**: On the very first separation, the application will automatically download the necessary AI models. This requires an internet connection and may take some time depending on your speed. Subsequent runs will be offline.
- **Troubleshooting**: If you previously encountered NumPy errors during packaging, these have been addressed in the latest build spec (v1.1+).
