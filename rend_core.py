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
import registry

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


# Output formats: (file extension, soundfile format, subtype).
#   wav  — 32-bit float: preserves samples beyond +/-1.0 with zero loss, at
#          the cost of large files. The summed karaoke accompaniment routinely
#          overshoots +/-1.0, so this is the safe default.
#   flac — 24-bit lossless PCM: ~half the size of float WAV. FLAC has no float
#          subtype, so samples beyond +/-1.0 are clipped by libsndfile on write
#          (only the karaoke accompaniment sum ever reaches that range).
OUTPUT_FORMATS = {
    "wav":  (".wav",  "WAV",  "FLOAT"),
    "flac": (".flac", "FLAC", "PCM_24"),
}


def save_stems(separated, output_folder, samplerate, fmt="wav"):
    """Save each stem tensor as <stem>.<ext> in *output_folder*.

    *fmt* is a key of OUTPUT_FORMATS ("wav" or "flac"). Saved manually via
    soundfile to avoid triggering any internal demucs MP3 calls (see
    CONTEXT.md: never use TorchAudio or demucs' own save).
    """
    try:
        ext, sf_format, subtype = OUTPUT_FORMATS[fmt]
    except KeyError:
        raise ValueError(f"Unsupported output format: {fmt!r} (choose from {list(OUTPUT_FORMATS)})")
    os.makedirs(output_folder, exist_ok=True)
    for stem, source in separated.items():
        filepath = os.path.join(output_folder, f"{stem}{ext}")
        # Convert to numpy and transpose for soundfile
        audio_np = source.cpu().numpy().transpose(1, 0)
        sf.write(filepath, audio_np, samplerate, format=sf_format, subtype=subtype)


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


def select_device():
    """Return "cuda" if an NVIDIA GPU is usable, else "cpu".

    Demucs runs several times faster on a CUDA GPU. The probe is cheap and its
    result is stable for the process lifetime, so callers may cache it. Any
    failure (no torch CUDA build, driver mismatch) falls back to CPU rather
    than raising.
    """
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


# ── Separation engines ────────────────────────────────────────────────────────
# A model's `engine` (see registry.py) selects how it runs. Only "demucs" is
# wired today; the abstraction exists so a RoFormer/audio-separator engine can
# be added later without touching SeparationThread. Each engine takes the
# driving SeparationThread as its request context — it reads the input file,
# resolved device, model name, and options from it, drives progress through
# req.handle_progress, and writes the finished stems to req.output_folder.


class Engine:
    """Base class: turn req.input_file into stem files under req.output_folder."""
    name = "base"

    def separate(self, req):
        raise NotImplementedError


class DemucsEngine(Engine):
    """In-process Demucs separation (demucs.api). Weights are auto-downloaded by
    demucs on first use; the import is deferred so rend_core stays importable in
    CI without demucs installed (see module docstring)."""
    name = "demucs"

    def separate(self, req):
        import demucs.api  # deferred — see module docstring

        # We explicitly do NOT ask for MP3 support here to avoid the missing
        # library crash. shifts=1 is default, >1 is slower but better quality.
        separator = demucs.api.Separator(
            model=req.model_name,
            device=req.device,
            shifts=req.shifts,
            progress=False,   # tqdm writes to stderr which is a DummyStream in --noconsole mode;
                              # our callback drives the progress bar instead
            callback=req.handle_progress,
        )

        req.callback(f"Loading {req.model_name} on {req.device.upper()}... (First run takes time)", 0.1)
        origin, separated = separator.separate_audio_file(req.input_file)

        req.callback(f"Saving {req.output_format.upper()} files...", 0.9)
        # Karaoke Mode: reduce to vocals + accompaniment before saving.
        if req.two_stems:
            separated = karaoke_mixdown(separated, req.model_name)
        save_stems(separated, req.output_folder, separator.samplerate, req.output_format)


_ENGINES = {
    DemucsEngine.name: DemucsEngine,
}


def get_engine(engine_name):
    """Return an Engine instance for *engine_name*.

    Raises ValueError for a known-but-unwired engine (e.g. "roformer" before its
    phase lands), so the failure is a clear message rather than a KeyError.
    """
    try:
        return _ENGINES[engine_name]()
    except KeyError:
        raise ValueError(
            f"The '{engine_name}' engine is not available in this build yet."
        )


def engine_for_model(model_name):
    """Resolve the engine name for *model_name* via the registry.

    Unknown names default to "demucs" so a raw Demucs model string (or any
    future demucs variant not yet catalogued) still runs.
    """
    model = registry.get_model(model_name)
    return model.engine if model else "demucs"


class SeparationThread(threading.Thread):
    def __init__(self, input_file, output_folder, model_name, shifts, two_stems,
                 callback, stop_event, device=None, output_format="wav"):
        super().__init__()
        self.input_file = input_file
        self.output_folder = output_folder
        self.model_name = model_name
        self.shifts = shifts
        self.two_stems = two_stems
        self.callback = callback
        self.stop_event = stop_event
        # device=None → auto-detect at run time; output_format is a save_stems key
        self.device = device
        self.output_format = output_format

    def run(self):
        try:
            # Auto-detect the device (CUDA GPU when present) unless one was
            # passed in; falls back to CPU, which is the safe default. Resolved
            # once here so the engine sees a concrete device string.
            self.device = self.device or select_device()

            # Dispatch to the engine this model uses (only "demucs" is wired
            # today). The engine reads its inputs and options from `self` and
            # writes the finished stems into self.output_folder.
            engine = get_engine(engine_for_model(self.model_name))
            engine.separate(self)

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
