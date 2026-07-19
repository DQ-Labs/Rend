"""Core separation logic for Rend.

This module must never import tkinter/customtkinter so it can be imported and
tested headlessly in CI (see tests/test_rend_core.py). demucs.api is imported
lazily inside SeparationThread.run() because demucs is installed from source
(setup_dev.ps1 / the build workflow) and is not available in the test job.
"""

import os
import socket
import subprocess
import threading
import time
import traceback

import torch
import soundfile as sf

import config

LOG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), config.APP_NAME, "error.log")


def log_error(message):
    """Append an error with traceback to a log file the user can send with bug reports."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{message}\n")
    except Exception:
        pass


def output_folder_for(input_file):
    """Return the stems output folder for *input_file*: <name>_stems next to it."""
    folder_name = os.path.splitext(os.path.basename(input_file))[0] + "_stems"
    return os.path.join(os.path.dirname(input_file), folder_name)


def progress_fraction(segment_offset, audio_length):
    """Map demucs segment progress into the 0.15 → 0.88 progress-bar band.

    The band leaves headroom for the "Loading model…" (0.1) and "Saving…"
    (0.9) bookends reported around the separation itself.
    """
    frac = min(segment_offset / max(audio_length, 1), 1.0)
    return 0.15 + frac * 0.73


def karaoke_mixdown(separated, model_name):
    """Reduce a stem dict to {vocals, accompaniment} for Karaoke Mode.

    Demucs (4-source) returns: drums, bass, other, vocals. Everything except
    vocals is summed into "accompaniment". The input dict is not modified.
    """
    # Guard: not all models produce a "vocals" stem (e.g. htdemucs_6s
    # uses different internal naming). Fail clearly instead of KeyError.
    if "vocals" not in separated:
        raise ValueError(
            f"The '{model_name}' model does not produce a 'vocals' "
            "stem and cannot be used with Karaoke Mode."
        )
    separated = dict(separated)
    vocals = separated.pop("vocals")
    accompaniment = torch.zeros_like(vocals)
    for stem, source in separated.items():
        accompaniment += source
    return {"vocals": vocals, "accompaniment": accompaniment}


def save_stems(separated, output_folder, samplerate):
    """Save each stem tensor as <stem>.wav in *output_folder*.

    Saved manually via soundfile to avoid triggering any internal demucs
    MP3 calls (see CONTEXT.md: never use TorchAudio or demucs' own save).
    """
    os.makedirs(output_folder, exist_ok=True)
    for stem, source in separated.items():
        filepath = os.path.join(output_folder, f"{stem}.wav")
        # Convert to numpy and transpose for soundfile
        audio_np = source.cpu().numpy().transpose(1, 0)
        # subtype="FLOAT": PCM_16 (the WAV default) hard-clips samples
        # outside +/-1.0, which the summed accompaniment routinely exceeds
        sf.write(filepath, audio_np, samplerate, subtype="FLOAT")


def check_ffmpeg():
    """Return True if ffmpeg is runnable from PATH."""
    try:
        # Prevent black window popping up on Windows
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        return True
    except Exception:
        return False


def check_online(host="dl.fbaipublicfiles.com", port=443, timeout=3):
    """Return True if the model-weights download host is reachable.

    Probes the host the weights actually download from, so the status light
    reflects whether a first-run download can succeed.
    """
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False


class SeparationThread(threading.Thread):
    def __init__(self, input_file, output_folder, model_name, shifts, two_stems, callback, stop_event):
        super().__init__()
        self.input_file = input_file
        self.output_folder = output_folder
        self.model_name = model_name
        self.shifts = shifts
        self.two_stems = two_stems
        self.callback = callback
        self.stop_event = stop_event

    def run(self):
        try:
            import demucs.api  # deferred — see module docstring

            # 1. Configure the Separator
            # device="cpu" is safer for compatibility.
            # We explicitly do NOT ask for MP3 support here to avoid the missing library crash.
            # shifts=1 is default, >1 is slower but better quality
            separator = demucs.api.Separator(
                model=self.model_name,
                device="cpu",
                shifts=self.shifts,
                progress=False,   # tqdm writes to stderr which is a DummyStream in --noconsole mode;
                                  # our callback drives the progress bar instead
                callback=self.handle_progress
            )

            # 2. Start Separation
            self.callback(f"Loading {self.model_name}... (First run takes time)", 0.1)
            origin, separated = separator.separate_audio_file(self.input_file)

            # 3. Save the Stems
            self.callback("Saving WAV files...", 0.9)

            # Karaoke Mode: If two_stems is True, we want "vocals" and "accompaniment"
            if self.two_stems:
                separated = karaoke_mixdown(separated, self.model_name)

            save_stems(separated, self.output_folder, separator.samplerate)

            self.callback("Done!", 1.0)

        except KeyboardInterrupt:
            self.callback("Cancelled.", 0.0)
        except Exception as e:
            log_error(traceback.format_exc())
            self.callback(f"Error: {str(e)}", 0.0)

    def handle_progress(self, data):
        # Demucs calls this after each audio segment is processed.
        # data = {'state': 'start'|'end', 'segment': offset, 'audio_length': total, ...}
        # We only act on 'end' events so we report completed work, not started work.
        if self.stop_event.is_set():
            raise KeyboardInterrupt
        if data.get('state') == 'end':
            # 'segment_offset' is the frame offset of the completed chunk;
            # 'audio_length' is the total frame count — both always present per the API.
            offset = data.get('segment_offset', 0)
            audio_length = data.get('audio_length', 1)
            self.callback("Processing...", progress_fraction(offset, audio_length))
