"""Architecture + inference parameters for the vendored RoFormer models.

Upstream ships these as YAML. They're transcribed to plain dicts here so Rend
needs no yaml parser and PyInstaller has no data files to bundle — the config is
just code. Values must match the checkpoint exactly or the weights won't load.

Provenance: becruily_guitar mirrors `config_guitar_becruily.yaml` as vendored
(and patched) by mimrock/musichammer — notably `mlp_expansion_factor: 1`, which
this checkpoint requires and upstream's default (4) gets wrong.
"""

BECRUILY_GUITAR = {
    "arch": "mel_band_roformer",
    # Passed straight to MelBandRoformer(**model).
    "model": {
        "dim": 256,
        "depth": 4,
        "stereo": True,
        "num_stems": 1,
        "time_transformer_depth": 1,
        "freq_transformer_depth": 1,
        "num_bands": 60,
        "dim_head": 64,
        "heads": 8,
        "attn_dropout": 0.0,
        "ff_dropout": 0.0,
        "flash_attn": True,
        "dim_freqs_in": 1025,
        "sample_rate": 44100,
        "stft_n_fft": 2048,
        "stft_hop_length": 441,
        "stft_win_length": 2048,
        "stft_normalized": False,
        "mask_estimator_depth": 2,
        "mlp_expansion_factor": 1,
        "multi_stft_resolution_loss_weight": 1.0,
        "multi_stft_resolutions_window_sizes": (4096, 2048, 1024, 512, 256),
        "multi_stft_hop_size": 147,
        "multi_stft_normalized": False,
    },
    "audio": {
        "sample_rate": 44100,
        "chunk_size": 485100,   # ~11s at 44.1kHz
    },
    "inference": {
        "num_overlap": 2,       # 50% overlap → Hann windows sum to 1
    },
    # num_stems=1 models predict one target; the other stem is the remainder.
    "stems": {
        "target": "guitar",
        "complement": "other",
    },
}

BECRUILY_INSTRUMENTAL = {
    "arch": "mel_band_roformer",
    "model": {
        "dim": 384,
        "depth": 6,
        "stereo": True,
        "num_stems": 1,
        "time_transformer_depth": 1,
        "freq_transformer_depth": 1,
        "num_bands": 60,
        "dim_head": 64,
        "heads": 8,
        "attn_dropout": 0.0,
        "ff_dropout": 0.0,
        "flash_attn": True,
        "dim_freqs_in": 1025,
        "sample_rate": 44100,
        "stft_n_fft": 2048,
        "stft_hop_length": 441,
        "stft_win_length": 2048,
        "stft_normalized": False,
        "mask_estimator_depth": 2,
        # NOTE: deliberately no mlp_expansion_factor — this checkpoint was trained
        # with the upstream default (4), unlike the guitar model which needs 1.
        "multi_stft_resolution_loss_weight": 1.0,
        "multi_stft_resolutions_window_sizes": (4096, 2048, 1024, 512, 256),
        "multi_stft_hop_size": 147,
        "multi_stft_normalized": False,
    },
    "audio": {
        "sample_rate": 44100,
        "chunk_size": 352800,   # 8s at 44.1kHz — smaller than the guitar model's
    },
    "inference": {
        "num_overlap": 2,
    },
    "stems": {
        "target": "instrumental",
        "complement": "vocals",
    },
}

CONFIGS = {
    "becruily_guitar": BECRUILY_GUITAR,
    "becruily_instrumental": BECRUILY_INSTRUMENTAL,
}


def get_config(key):
    """Return the config dict for *key*, or raise a clear error."""
    try:
        return CONFIGS[key]
    except KeyError:
        raise ValueError(
            f"No vendored RoFormer config named {key!r} (have: {sorted(CONFIGS)})"
        )
