"""Headless tests for rend_core — no GUI, no demucs, no model downloads."""

import os
import threading

import pytest
import soundfile as sf
import torch

import rend_core
from rend_core import (
    DemucsEngine,
    Engine,
    SeparationThread,
    engine_for_model,
    get_engine,
    karaoke_mixdown,
    output_folder_for,
    progress_fraction,
    save_stems,
    select_device,
)


# ── Output folder naming ──────────────────────────────────────────────────────

def test_output_folder_is_named_after_input_file():
    input_file = os.path.join("music", "albums", "song.mp3")
    assert output_folder_for(input_file) == os.path.join("music", "albums", "song_stems")

def test_output_folder_strips_only_last_extension():
    input_file = os.path.join("music", "my.song.final.wav")
    assert output_folder_for(input_file) == os.path.join("music", "my.song.final_stems")

def test_output_folder_for_bare_filename():
    assert output_folder_for("song.flac") == "song_stems"


# ── Progress fraction mapping ─────────────────────────────────────────────────

def test_progress_starts_at_band_floor():
    assert progress_fraction(0, 44100) == pytest.approx(0.15)

def test_progress_ends_at_band_ceiling():
    assert progress_fraction(44100, 44100) == pytest.approx(0.88)

def test_progress_midpoint_maps_into_band():
    assert progress_fraction(22050, 44100) == pytest.approx(0.15 + 0.5 * 0.73)

def test_progress_clamps_offset_beyond_length():
    # demucs segments can overshoot the total on the final chunk
    assert progress_fraction(50000, 44100) == pytest.approx(0.88)

def test_progress_survives_zero_audio_length():
    # must not raise ZeroDivisionError
    assert 0.15 <= progress_fraction(0, 0) <= 0.88

def test_progress_is_monotonic():
    values = [progress_fraction(i, 100) for i in range(0, 101, 10)]
    assert values == sorted(values)


# ── Karaoke mixdown ───────────────────────────────────────────────────────────

def _four_stem_dict():
    torch.manual_seed(0)
    return {
        stem: torch.randn(2, 16)  # (channels, frames), tiny on purpose
        for stem in ("drums", "bass", "other", "vocals")
    }

def test_karaoke_requires_vocals_stem():
    separated = {"guitar": torch.zeros(2, 16), "piano": torch.zeros(2, 16)}
    with pytest.raises(ValueError, match="htdemucs_6s"):
        karaoke_mixdown(separated, "htdemucs_6s")

def test_karaoke_returns_exactly_two_stems():
    result = karaoke_mixdown(_four_stem_dict(), "htdemucs")
    assert set(result) == {"vocals", "accompaniment"}

def test_karaoke_accompaniment_is_sum_of_non_vocal_stems():
    separated = _four_stem_dict()
    expected = separated["drums"] + separated["bass"] + separated["other"]
    result = karaoke_mixdown(separated, "htdemucs")
    assert torch.allclose(result["accompaniment"], expected)
    assert torch.equal(result["vocals"], separated["vocals"])

def test_karaoke_does_not_mutate_input_dict():
    separated = _four_stem_dict()
    karaoke_mixdown(separated, "htdemucs")
    assert set(separated) == {"drums", "bass", "other", "vocals"}


# ── Stem saving ───────────────────────────────────────────────────────────────

def test_save_stems_writes_float_wavs_without_clipping(tmp_path):
    # Accompaniment sums routinely exceed +/-1.0; the FLOAT subtype must
    # preserve those samples instead of hard-clipping like PCM_16 would.
    out_dir = tmp_path / "song_stems"
    loud = torch.full((2, 32), 1.5)
    save_stems({"accompaniment": loud, "vocals": torch.zeros(2, 32)}, str(out_dir), 44100)

    assert sorted(p.name for p in out_dir.iterdir()) == ["accompaniment.wav", "vocals.wav"]
    audio, samplerate = sf.read(out_dir / "accompaniment.wav")
    assert samplerate == 44100
    assert audio.shape == (32, 2)  # transposed to (frames, channels)
    assert audio.max() == pytest.approx(1.5)


def test_save_stems_defaults_to_wav():
    # The extension/format is opt-in; the default must stay WAV for back-compat.
    assert rend_core.OUTPUT_FORMATS["wav"][0] == ".wav"


def test_save_stems_writes_flac_with_flac_extension(tmp_path):
    out_dir = tmp_path / "song_stems"
    quiet = torch.full((2, 32), 0.5)
    save_stems({"vocals": quiet}, str(out_dir), 44100, fmt="flac")

    assert [p.name for p in out_dir.iterdir()] == ["vocals.flac"]
    audio, samplerate = sf.read(out_dir / "vocals.flac")
    assert samplerate == 44100
    assert audio.shape == (32, 2)
    # 24-bit lossless PCM round-trips a 0.5 sample essentially exactly.
    assert audio.max() == pytest.approx(0.5, abs=1e-4)


def test_save_stems_flac_clips_beyond_unity(tmp_path):
    # FLAC has no float subtype: samples past +/-1.0 clip on write. Documented
    # behaviour — WAV FLOAT remains the choice for karaoke-accompaniment headroom.
    out_dir = tmp_path / "song_stems"
    save_stems({"accompaniment": torch.full((2, 32), 1.5)}, str(out_dir), 44100, fmt="flac")
    audio, _ = sf.read(out_dir / "accompaniment.flac")
    assert audio.max() == pytest.approx(1.0, abs=1e-3)


def test_save_stems_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError, match="mp3"):
        save_stems({"vocals": torch.zeros(2, 32)}, str(tmp_path), 44100, fmt="mp3")


# ── Device selection ──────────────────────────────────────────────────────────

def test_select_device_prefers_cuda_when_available(monkeypatch):
    monkeypatch.setattr(rend_core.torch.cuda, "is_available", lambda: True)
    assert select_device() == "cuda"


def test_select_device_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(rend_core.torch.cuda, "is_available", lambda: False)
    assert select_device() == "cpu"


def test_select_device_survives_probe_failure(monkeypatch):
    # A broken CUDA build can raise from is_available(); must degrade to CPU.
    def boom():
        raise RuntimeError("no CUDA driver")
    monkeypatch.setattr(rend_core.torch.cuda, "is_available", boom)
    assert select_device() == "cpu"


# ── Engine dispatch ───────────────────────────────────────────────────────────

def test_get_engine_returns_demucs_engine():
    assert isinstance(get_engine("demucs"), DemucsEngine)


def test_get_engine_unwired_engine_raises_clear_error():
    # "roformer" is catalogued but not wired until a later phase.
    with pytest.raises(ValueError, match="roformer"):
        get_engine("roformer")


def test_engine_for_model_maps_demucs_models():
    assert engine_for_model("htdemucs") == "demucs"
    assert engine_for_model("mdx_extra") == "demucs"


def test_engine_for_model_maps_downloadable_to_roformer():
    assert engine_for_model("bs_roformer_sw") == "roformer"


def test_engine_for_unknown_model_defaults_to_demucs():
    # A raw/uncatalogued model string still routes to the demucs engine.
    assert engine_for_model("some_future_demucs_variant") == "demucs"


def _thread_with(monkeypatch, engine_cls, model_name="htdemucs"):
    """Build a SeparationThread whose demucs engine slot is *engine_cls*, and
    capture its callback events. Runs synchronously via run() — no real thread."""
    monkeypatch.setitem(rend_core._ENGINES, "demucs", engine_cls)
    monkeypatch.setattr(rend_core, "log_error", lambda *a, **k: None)
    events = []
    t = SeparationThread(
        input_file="in.wav", output_folder="out", model_name=model_name,
        shifts=1, two_stems=False,
        callback=lambda s, p: events.append((s, p)),
        stop_event=threading.Event(),
    )
    return t, events


def test_run_dispatches_to_engine_and_reports_done(monkeypatch):
    received = []

    class FakeEngine(Engine):
        name = "demucs"
        def separate(self, req):
            received.append(req)

    t, events = _thread_with(monkeypatch, FakeEngine)
    t.run()

    assert received == [t]                     # the engine got the driving thread
    assert t.device in ("cpu", "cuda")         # device resolved to a concrete value
    assert events[-1] == ("Done!", 1.0)


def test_run_reports_cancelled_on_keyboard_interrupt(monkeypatch):
    class CancelEngine(Engine):
        name = "demucs"
        def separate(self, req):
            raise KeyboardInterrupt

    t, events = _thread_with(monkeypatch, CancelEngine)
    t.run()

    assert ("Cancelled.", 0.0) in events
    assert ("Done!", 1.0) not in events


def test_run_reports_error_and_logs_on_exception(monkeypatch):
    class BoomEngine(Engine):
        name = "demucs"
        def separate(self, req):
            raise RuntimeError("kaboom")

    logged = []
    monkeypatch.setitem(rend_core._ENGINES, "demucs", BoomEngine)
    monkeypatch.setattr(rend_core, "log_error", lambda msg: logged.append(msg))
    events = []
    t = SeparationThread(
        input_file="in.wav", output_folder="out", model_name="htdemucs",
        shifts=1, two_stems=False,
        callback=lambda s, p: events.append((s, p)),
        stop_event=threading.Event(),
    )
    t.run()

    assert events[-1] == ("Error: kaboom", 0.0)
    assert logged and "kaboom" in logged[0]


def test_run_honours_explicitly_passed_device(monkeypatch):
    # If a device is supplied, run() must not overwrite it with auto-detection.
    seen = []

    class RecordEngine(Engine):
        name = "demucs"
        def separate(self, req):
            seen.append(req.device)

    monkeypatch.setitem(rend_core._ENGINES, "demucs", RecordEngine)
    t = SeparationThread(
        input_file="in.wav", output_folder="out", model_name="htdemucs",
        shifts=1, two_stems=False, callback=lambda s, p: None,
        stop_event=threading.Event(), device="cuda",
    )
    t.run()
    assert seen == ["cuda"]
