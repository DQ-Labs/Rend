"""Headless tests for rend_core — no GUI, no demucs, no model downloads."""

import os

import pytest
import soundfile as sf
import torch

from rend_core import (
    karaoke_mixdown,
    output_folder_for,
    progress_fraction,
    save_stems,
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
