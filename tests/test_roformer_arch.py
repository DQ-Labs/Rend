"""Smoke test for the vendored Mel-Band RoFormer architecture.

Proves the vendored code imports and runs a forward pass with only the light
deps (einops, rotary-embedding-torch, beartype) — no librosa — which is the
whole premise of the in-process RoFormer engine. A small config keeps it fast;
the real checkpoint/config is exercised end-to-end by the engine smoke test.
"""

import sys

import torch

from roformer_source.mel_band_roformer import MelBandRoformer


def _small_model():
    # num_bands=60 keeps full FFT-bin coverage (the model asserts it); dim/depth
    # are shrunk just for speed.
    return MelBandRoformer(
        dim=32, depth=1, stereo=True, num_stems=1,
        time_transformer_depth=1, freq_transformer_depth=1,
        num_bands=60, dim_head=8, heads=4,
        attn_dropout=0.0, ff_dropout=0.0, flash_attn=True,
        dim_freqs_in=1025, sample_rate=44100,
        stft_n_fft=2048, stft_hop_length=441, stft_win_length=2048,
        stft_normalized=False, mask_estimator_depth=1,
        mlp_expansion_factor=1,
    )


def test_arch_runs_forward_and_never_imports_librosa():
    model = _small_model().eval()
    x = torch.randn(1, 2, 8192)  # (batch, stereo, samples)
    with torch.no_grad():
        out = model(x)

    assert out.shape[0] == 1 and out.shape[1] == 2   # (batch, stereo, samples)
    assert out.shape[-1] > 0
    assert torch.isfinite(out).all()
    # The whole point of vendoring mel_filter: librosa must never be pulled in.
    assert "librosa" not in sys.modules
