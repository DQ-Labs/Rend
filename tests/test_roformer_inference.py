"""Tests for the chunked RoFormer inference loop.

Uses a stand-in "model" instead of the real network, so the chunking, Hann
overlap-add, progress reporting and cancellation are all verified headlessly —
no checkpoint, no download, no heavy forward passes.
"""

import pytest
import torch

from roformer_source.inference import separate_chunked


class _IdentityModel:
    """Returns its input unchanged, so overlap-add must reconstruct the signal."""
    def __call__(self, x):
        return x


class _CountingModel(_IdentityModel):
    def __init__(self):
        self.calls = 0

    def __call__(self, x):
        self.calls += 1
        return x


def _audio(samples=5000, channels=2):
    torch.manual_seed(0)
    return torch.randn(channels, samples)


# ── Overlap-add correctness ───────────────────────────────────────────────────

def test_identity_model_reconstructs_the_signal():
    # With Hann windows at 50% overlap and weight normalization, passing audio
    # straight through must return it essentially unchanged.
    audio = _audio()
    out = separate_chunked(_IdentityModel(), audio, chunk_size=1024, num_overlap=2)

    assert out.shape == audio.shape
    assert torch.allclose(out, audio, atol=1e-5)


def test_output_length_matches_input_for_non_multiple_lengths():
    # Length deliberately not a multiple of the chunk/step size.
    audio = _audio(samples=3333)
    out = separate_chunked(_IdentityModel(), audio, chunk_size=512, num_overlap=2)
    assert out.shape == audio.shape


def test_reconstruction_holds_at_higher_overlap():
    audio = _audio(samples=4096)
    out = separate_chunked(_IdentityModel(), audio, chunk_size=1024, num_overlap=4)
    assert torch.allclose(out, audio, atol=1e-5)


def test_audio_shorter_than_one_chunk_is_handled():
    audio = _audio(samples=300)
    out = separate_chunked(_IdentityModel(), audio, chunk_size=2048, num_overlap=2)
    assert out.shape == audio.shape
    assert torch.isfinite(out).all()


# ── Progress ──────────────────────────────────────────────────────────────────

def test_progress_is_monotonic_and_finishes_at_one():
    seen = []
    separate_chunked(_IdentityModel(), _audio(), chunk_size=1024, num_overlap=2,
                     progress=seen.append)

    assert seen, "progress should be reported at least once"
    assert seen == sorted(seen)
    assert seen[-1] == pytest.approx(1.0)
    assert all(0.0 < f <= 1.0 for f in seen)


# ── Cancellation ──────────────────────────────────────────────────────────────

def test_should_stop_raises_before_any_work():
    model = _CountingModel()
    with pytest.raises(KeyboardInterrupt):
        separate_chunked(model, _audio(), chunk_size=1024, num_overlap=2,
                         should_stop=lambda: True)
    assert model.calls == 0  # cancelled before the first forward pass


def test_should_stop_midway_stops_early():
    model = _CountingModel()

    def stop_after_two():
        return model.calls >= 2

    with pytest.raises(KeyboardInterrupt):
        separate_chunked(model, _audio(samples=20000), chunk_size=1024,
                         num_overlap=2, should_stop=stop_after_two)
    assert model.calls == 2
