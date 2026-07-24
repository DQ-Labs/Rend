"""Core separation logic for Rend.

This module must never import tkinter/customtkinter so it can be imported and
tested headlessly in CI (see tests/test_rend_core.py). demucs.api is imported
lazily inside SeparationThread.run() because demucs is installed from source
(setup_dev.ps1 / the build workflow) and is not available in the test job.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import torch
import soundfile as sf

import config
import downloader
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


def ffmpeg_exe():
    """Return the ffmpeg executable to invoke.

    PATH first, then the copy shipped alongside the app — the PyInstaller bundle
    dir when frozen, or the project root for source installs (where the README
    tells users to drop ffmpeg.exe). Windows does not search the working
    directory for executables, so the explicit fallback is what makes a source
    install work at all.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    local = os.path.join(base, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return local if os.path.exists(local) else "ffmpeg"


def check_ffmpeg():
    """Return True if ffmpeg is runnable (PATH or bundled/project-root copy)."""
    try:
        # Prevent black window popping up on Windows
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(
            [ffmpeg_exe(), "-version"],
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


def decode_audio(path, target_sr, channels=2):
    """Decode *path* to a float32 (channels, samples) tensor at *target_sr*.

    Routed through the bundled ffmpeg so every input Rend accepts (MP3/WAV/FLAC)
    is handled — along with resampling and channel normalization — without
    adding a resampler dependency.
    """
    fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(
            [ffmpeg_exe(), "-v", "error", "-y", "-i", path,
             "-ac", str(channels), "-ar", str(target_sr), "-c:a", "pcm_f32le", tmp_wav],
            check=True, capture_output=True, creationflags=creationflags,
        )
        data, _ = sf.read(tmp_wav, dtype="float32", always_2d=True)  # (frames, channels)
    finally:
        try:
            os.remove(tmp_wav)
        except OSError:
            pass
    return torch.from_numpy(data.T.copy())  # (channels, samples)


class RoformerEngine(Engine):
    """In-process RoFormer separation using the vendored architecture.

    Only the checkpoint is downloaded (sha256-verified, on first use); the model
    code and config are vendored in roformer_source/, so this needs no external
    tool and runs in Rend's own environment — which also gives real per-chunk
    progress and cancellation, like the demucs engine.
    """
    name = "roformer"

    def separate(self, req):
        # Deferred so the vendored model code is imported only when a RoFormer
        # model actually runs.
        from roformer_source import inference as roformer_inference
        from roformer_source import model_configs

        model_rec = registry.get_model(req.model_name)
        if model_rec is None or not model_rec.arch_config:
            raise ValueError(f"Model {req.model_name!r} has no vendored RoFormer config.")
        cfg = model_configs.get_config(model_rec.arch_config)

        # 1. Weights — downloaded on first use, rejected on sha256 mismatch.
        if not registry.is_installed(model_rec):
            def dl_progress(done, total):
                frac = (done / total) if total else 0.0
                req.callback(f"Downloading model... {int(frac * 100)}%", 0.02 + 0.08 * frac)

            req.callback(f"Downloading {model_rec.display_name}...", 0.02)
            downloader.download_model(model_rec, progress=dl_progress)

        req.callback(f"Loading {model_rec.display_name} on {req.device.upper()}...", 0.1)
        model = roformer_inference.build_model(cfg)
        missing, _unexpected = roformer_inference.load_checkpoint(
            model, str(registry.model_file_path(model_rec.files[0])), device=req.device,
        )
        if missing:
            raise RuntimeError(
                f"Checkpoint does not match the vendored architecture "
                f"({len(missing)} missing keys, e.g. {missing[:3]})."
            )
        model.eval().to(req.device)

        # 2. Decode at the model's sample rate.
        sr = cfg["audio"]["sample_rate"]
        audio = decode_audio(req.input_file, sr)

        # 3. Chunked inference, reported into the same 0.15-0.88 band as demucs.
        target = roformer_inference.separate_chunked(
            model, audio,
            chunk_size=cfg["audio"]["chunk_size"],
            num_overlap=cfg["inference"]["num_overlap"],
            progress=lambda frac: req.callback("Separating...", progress_fraction(frac, 1.0)),
            should_stop=req.stop_event.is_set,
            device=req.device,
        )

        # 4. A num_stems=1 model predicts the target; the rest is the remainder.
        req.callback(f"Saving {req.output_format.upper()} files...", 0.9)
        save_stems(
            {cfg["stems"]["target"]: target,
             cfg["stems"]["complement"]: audio - target},
            req.output_folder, sr, req.output_format,
        )


_ENGINES = {
    DemucsEngine.name: DemucsEngine,
    RoformerEngine.name: RoformerEngine,
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
