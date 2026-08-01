"""Dependency-free mel filterbank — a drop-in for `librosa.filters.mel`.

MelBandRoformer only needs `librosa` for one call: building the mel filterbank
whose *support* (which FFT bins fall in each band) defines the band split. Pulling
in librosa would drag numba/llvmlite/scipy/scikit-learn into the app (~500 MB and a
PyInstaller headache), so this reimplements librosa's exact algorithm (htk=False,
norm="slaney", fmin=0, fmax=sr/2) with only numpy. Validated byte-for-byte against
real librosa in tests/test_mel_filter.py (skipped where librosa isn't installed).
"""

import numpy as np


def _hz_to_mel(freqs):
    """Slaney mel scale (librosa default, htk=False)."""
    freqs = np.asanyarray(freqs, dtype=float)
    f_sp = 200.0 / 3
    mels = freqs / f_sp
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    log_t = freqs >= min_log_hz
    mels[log_t] = min_log_mel + np.log(freqs[log_t] / min_log_hz) / logstep
    return mels


def _mel_to_hz(mels):
    """Inverse of _hz_to_mel (Slaney)."""
    mels = np.asanyarray(mels, dtype=float)
    f_sp = 200.0 / 3
    freqs = f_sp * mels
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    log_t = mels >= min_log_mel
    freqs[log_t] = min_log_hz * np.exp(logstep * (mels[log_t] - min_log_mel))
    return freqs


def _mel_frequencies(n_mels, fmin, fmax):
    min_mel = _hz_to_mel(np.array([fmin]))[0]
    max_mel = _hz_to_mel(np.array([fmax]))[0]
    return _mel_to_hz(np.linspace(min_mel, max_mel, n_mels))


def mel(sr, n_fft, n_mels, fmin=0.0, fmax=None):
    """Return an (n_mels, 1 + n_fft // 2) Slaney-normalized mel filterbank.

    Mirrors `librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=n_mels)` with librosa's
    defaults. The exact weights only scale the bands; the >0 support (all the model
    consumes) matches librosa.
    """
    if fmax is None:
        fmax = sr / 2.0

    fftfreqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)          # (1 + n_fft//2,)
    mel_f = _mel_frequencies(n_mels + 2, fmin, fmax)       # band edges

    fdiff = np.diff(mel_f)
    ramps = np.subtract.outer(mel_f, fftfreqs)

    weights = np.zeros((n_mels, len(fftfreqs)), dtype=np.float32)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0.0, np.minimum(lower, upper))

    # Slaney normalization: make each band's area ~constant.
    enorm = 2.0 / (mel_f[2 : n_mels + 2] - mel_f[:n_mels])
    weights *= enorm[:, np.newaxis]
    return weights
