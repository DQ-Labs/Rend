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

## Building from Source

To create a standalone EXE file using PyInstaller:

1. Ensure `pyinstaller` is installed:
   ```bash
   pip install pyinstaller
   ```

2. Run the build command using the provided spec file:
   ```bash
   pyinstaller VibeStem.spec
   ```
   This will use `VibeStem.spec` which is configured to:
   - Include `ffmpeg.exe` and `ffprobe.exe`.
   - Handle hidden imports for Demucs and Soundfile.
   - Create a single-file executable (`dist/VibeStem.exe`).
