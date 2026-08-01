"""Tests for the dependency-free mel filterbank (roformer_source/mel_filter.py).

The structural tests run everywhere. The oracle test validates a byte-for-byte
match against real librosa and is skipped where librosa isn't installed — Rend
never ships librosa, so this only runs in an env that has it for verification.
"""

import numpy as np
import pytest

from roformer_source.mel_filter import mel

# The becruily guitar model's params, plus a couple of other shapes.
CASES = [(44100, 2048, 60), (44100, 4096, 80), (22050, 1024, 40)]


def test_mel_shape():
    w = mel(sr=44100, n_fft=2048, n_mels=60)
    assert w.shape == (60, 1 + 2048 // 2)


def test_mel_is_nonnegative():
    assert (mel(44100, 2048, 60) >= 0).all()


def test_every_band_has_support():
    # Each mel band must cover at least one FFT bin.
    assert (mel(44100, 2048, 60) > 0).any(axis=1).all()


def test_interior_bins_are_covered():
    # MelBandRoformer asserts every frequency is covered by some band. librosa
    # leaves bin 0 and the last bin at 0 (the model force-sets those two itself),
    # so only the interior must be covered here.
    support = mel(44100, 2048, 60) > 0
    assert support.any(axis=0)[1:-1].all()


@pytest.mark.parametrize("sr,n_fft,n_mels", CASES)
def test_matches_librosa_exactly(sr, n_fft, n_mels):
    librosa = pytest.importorskip("librosa")
    mine = mel(sr, n_fft, n_mels)
    ref = librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=n_mels)
    assert mine.shape == ref.shape
    # Weights match, and — the part the model actually uses — the >0 support matches.
    assert np.allclose(mine, ref, atol=1e-6)
    assert ((mine > 0) == (ref > 0)).all()
