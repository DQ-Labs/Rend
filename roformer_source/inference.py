"""Chunked in-process inference for the vendored RoFormer models.

Long tracks don't fit in one forward pass, so audio is processed in overlapping
chunks and recombined with a Hann overlap-add. Kept free of Rend's GUI/engine
concerns — progress and cancellation are plain callbacks — so it's testable on
its own and reusable by the engine in rend_core.
"""

import torch
import torch.nn.functional as F


def build_model(cfg):
    """Instantiate the model described by *cfg* (see model_configs.py)."""
    if cfg["arch"] != "mel_band_roformer":
        raise ValueError(f"Unsupported RoFormer arch: {cfg['arch']!r}")
    from .mel_band_roformer import MelBandRoformer

    params = dict(cfg["model"])
    # Force the iSTFT to return exactly as many samples as it was given, so the
    # overlap-add below can assume output length == chunk length.
    params["match_input_audio_length"] = True
    return MelBandRoformer(**params)


def load_checkpoint(model, path, device="cpu"):
    """Load a checkpoint into *model*, returning (missing, unexpected) key lists.

    weights_only=True is deliberate: checkpoints are downloaded from third-party
    repos, and a plain torch.load would execute arbitrary pickle code.
    """
    state = torch.load(path, map_location=device, weights_only=True)
    if isinstance(state, dict):
        for wrapper in ("state_dict", "model", "model_state_dict"):
            if wrapper in state and isinstance(state[wrapper], dict):
                state = state[wrapper]
                break
    result = model.load_state_dict(state, strict=False)
    return list(result.missing_keys), list(result.unexpected_keys)


def separate_chunked(model, audio, chunk_size, num_overlap=2,
                     progress=None, should_stop=None, device="cpu"):
    """Run *model* over *audio* in overlapping chunks; return the target stem.

    *audio* is a (channels, samples) float tensor. *progress* is called with a
    0..1 fraction after each chunk; *should_stop* is polled before each chunk and
    raises KeyboardInterrupt when it returns True (Rend's cancel path).
    """
    channels, length = audio.shape
    step = max(chunk_size // max(num_overlap, 1), 1)

    # Pad by half a chunk each side so every real sample sits in the interior of
    # the overlap-add, where the Hann windows sum to 1 (no edge attenuation).
    pad = chunk_size // 2
    padded = F.pad(audio, (pad, pad))
    padded_len = padded.shape[-1]

    acc = torch.zeros(channels, padded_len, dtype=torch.float32)
    weights = torch.zeros(padded_len, dtype=torch.float32)
    window = torch.hann_window(chunk_size, dtype=torch.float32)

    starts = list(range(0, max(padded_len - chunk_size, 0) + 1, step))
    if not starts:
        starts = [0]

    for i, start in enumerate(starts):
        if should_stop is not None and should_stop():
            raise KeyboardInterrupt

        chunk = padded[:, start:start + chunk_size]
        n = chunk.shape[-1]
        if n < chunk_size:
            chunk = F.pad(chunk, (0, chunk_size - n))

        with torch.no_grad():
            out = model(chunk.unsqueeze(0).to(device))
        # num_stems=1 still yields (batch, channels, samples) here.
        out = out.reshape(channels, -1).float().cpu()

        m = min(out.shape[-1], chunk_size, padded_len - start)
        acc[:, start:start + m] += out[:, :m] * window[:m]
        weights[start:start + m] += window[:m]

        if progress is not None:
            progress((i + 1) / len(starts))

    acc /= weights.clamp(min=1e-8)
    return acc[:, pad:pad + length]
