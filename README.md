# Rend (VibeStem)

A simple Windows GUI for AI Music Stem Separation (Demucs) built with CustomTkinter.

## Features
- **Offline CPU Execution**: Uses `demucs` (htdemucs) for processing without requiring a GPU or internet connection for inference (after model download).
- **WAV Export**: Saves separated stems directly as WAV files using `soundfile`.
- **Dark Mode GUI**: Clean and modern interface powered by `customtkinter`.
- **Threaded Processing**: Keeps the UI responsive during separation.

## Installation

### Prerequisites
- **Python 3.10+**
- **FFmpeg**: `ffmpeg.exe` and `ffprobe.exe` must be present in the root directory.

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/DQ-Labs/VibeStem.git
   cd VibeStem
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. Install dependencies (including local Demucs source):
   ```bash
   pip install -r requirements.txt
   pip install -e ./demucs_source
   ```
   *(Note: Ensure `customtkinter`, `soundfile`, and other requirements are installed effectively)*

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
   pyinstaller VibeStem.spec --clean --noconfirm
   ```

   **Make sure to run this via your virtual environment's Python** (e.g., `.\venv\Scripts\python.exe -m PyInstaller ...`) if you have multiple Python versions installed.

   The `VibeStem.spec` file is configured to:
   - Include `demucs_source` in the path and data bundle.
   - Bundle `ffmpeg.exe` and `ffprobe.exe` binaries.
   - Handle hidden imports for `demucs` and `soundfile`.
   - Create a single-file executable (`dist/VibeStem.exe`).

## Known Behavior
- **Launch Time**: The final `.exe` takes approximately **30 seconds to launch**. This is normal behavior for a PyInstaller "one-file" build as it unpacks temporary files to a runtime directory.
- **First Run**: On the very first separation, the application will automatically download the necessary AI models. This requires an internet connection and may take some time depending on your speed. Subsequent runs will be offline.
