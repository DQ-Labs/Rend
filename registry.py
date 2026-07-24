"""Model registry: the catalog of separation models Rend can run.

This is the single source of truth for which models exist, which engine runs
them, their stems, and — for optional downloadable models — where the weights
come from and whether Rend may redistribute them.

Kept deliberately light: no torch, no GUI, no network. Importing this module
is cheap and fully testable headlessly (tests/test_registry.py). Actually
fetching/verifying weights lives in downloader.py, which builds on the records
defined here.

Engine wiring status: "demucs" and "roformer" (in-process, vendored — see
roformer_source/) are executed today. "bs_roformer" is catalog-only — its
metadata (URL, size, sha256, license) is real and verified, but that
architecture isn't vendored yet, so get_engine() rejects it with a clear error.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import config

# Where Rend-managed model weights are stored. Mirrors the error-log location
# (LOCALAPPDATA/Rend). Overridable via env so tests and power users can
# relocate it; read through the module attribute so monkeypatching works.
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / config.APP_NAME
MODELS_DIR = Path(os.environ.get("REND_MODELS_DIR", APP_DATA_DIR / "models"))


@dataclass(frozen=True)
class ModelFile:
    """One downloadable weight file, with the facts needed to verify it."""
    name: str          # local filename under MODELS_DIR
    url: str           # canonical source (the model author's own repo)
    size: int          # bytes, for progress + a cheap pre-hash sanity check
    sha256: str        # lowercase hex digest; the download is rejected if it differs


@dataclass(frozen=True)
class Model:
    id: str
    display_name: str
    engine: str                       # "demucs" (wired) | "roformer" (catalog-only for now)
    stems: tuple                      # canonical stem names this model produces
    weights: str                      # "engine_managed" (engine downloads) | "download" (Rend downloads)
    karaoke: bool                     # may be paired with Karaoke Mode (needs a clean vocals split)
    description: str = ""
    files: tuple = ()                 # ModelFile records; only for weights == "download"
    license: str = ""
    license_url: str = ""
    redistributable: bool = True      # may Rend bundle/rehost the weights? False → download-on-demand only
    arch_config: str = ""             # key into roformer_source.model_configs (engine == "roformer")
    cpu_x_realtime: float = 0.0       # rough CPU runtime as a multiple of song length, for ETA

    @property
    def downloadable(self) -> bool:
        """True if Rend fetches the weights itself (vs the engine managing them)."""
        return self.weights == "download"


# ── The catalog ───────────────────────────────────────────────────────────────
# Built-in Demucs models: weights are auto-downloaded by demucs on first use, so
# Rend manages no files for them. Descriptions mirror app.py's MODEL_INFO.
_DEMUCS_MODELS = (
    Model("htdemucs", "Demucs v4 (default)", "demucs",
          ("drums", "bass", "other", "vocals"), "engine_managed", karaoke=True,
          description="The Default. Balanced speed and quality.",
          license="MIT — Meta AI Research", license_url="https://github.com/adefossez/demucs"),
    Model("htdemucs_ft", "Demucs v4 fine-tuned", "demucs",
          ("drums", "bass", "other", "vocals"), "engine_managed", karaoke=True,
          description="Fine-Tuned. Slightly better vocals, but 4× slower.",
          license="MIT — Meta AI Research", license_url="https://github.com/adefossez/demucs"),
    Model("htdemucs_6s", "Demucs v4 (6 stems)", "demucs",
          ("drums", "bass", "other", "vocals", "guitar", "piano"), "engine_managed", karaoke=False,
          description="Six Stems — Drums, Bass, Vocals, Guitar, Piano, Other.",
          license="MIT — Meta AI Research", license_url="https://github.com/adefossez/demucs"),
    Model("mdx", "MDX", "demucs",
          ("drums", "bass", "other", "vocals"), "engine_managed", karaoke=True,
          description="Classic Model. Trained on MusDB HQ. Good baseline.",
          license="MIT — Meta AI Research", license_url="https://github.com/adefossez/demucs"),
    Model("mdx_extra", "MDX extra", "demucs",
          ("drums", "bass", "other", "vocals"), "engine_managed", karaoke=True,
          description="High Precision. Extra training data for complex mixes.",
          license="MIT — Meta AI Research", license_url="https://github.com/adefossez/demucs"),
    Model("mdx_q", "MDX quantized", "demucs",
          ("drums", "bass", "other", "vocals"), "engine_managed", karaoke=True,
          description="Quantized. Smaller download, slightly lower quality.",
          license="MIT — Meta AI Research", license_url="https://github.com/adefossez/demucs"),
)

# RoFormer models run in-process by the vendored engine (roformer_source/).
# Only the checkpoint is downloaded — the architecture and config are vendored —
# so these behave exactly like the Demucs models: weights fetched on first use.
_ROFORMER_MODELS = (
    Model("melband_instrumental", "Mel-RoFormer Vocals / Instrumental (becruily)", "roformer",
          ("instrumental", "vocals"), "download", karaoke=True,
          description="RoFormer vocal/instrumental split — noticeably cleaner than Demucs "
                      "for karaoke and backing tracks. Large download (~913 MB).",
          files=(ModelFile(
              "mel_band_roformer_instrumental_becruily.ckpt",
              "https://huggingface.co/becruily/mel-band-roformer-instrumental/resolve/main/"
              "mel_band_roformer_instrumental_becruily.ckpt",
              913106900,
              "a8da6632a1c25efb1c9be783ce9ea367d226d4b918cd6c3717c8b1d7a396041d",
          ),),
          license="None declared", license_url="https://huggingface.co/becruily/mel-band-roformer-instrumental",
          redistributable=False,
          arch_config="becruily_instrumental",
          cpu_x_realtime=5.1),   # measured on CPU: 20s clip in 102s (228M params)
    Model("melband_guitar", "Mel-RoFormer Guitar (becruily)", "roformer",
          ("guitar", "other"), "download", karaoke=False,
          description="RoFormer guitar isolation — markedly cleaner than Demucs on "
                      "distorted guitar. Small download, slower than Demucs on CPU.",
          files=(ModelFile(
              "becruily_guitar.ckpt",
              "https://huggingface.co/becruily/mel-band-roformer-guitar/resolve/main/becruily_guitar.ckpt",
              45142183,
              "83472bbf125774af5282d2e0b86df89eaf2dd45e8a4ec8d68e820ebf3e42a83c",
          ),),
          license="None declared", license_url="https://huggingface.co/becruily/mel-band-roformer-guitar",
          redistributable=False,
          arch_config="becruily_guitar",
          cpu_x_realtime=3.0),   # measured on CPU: 20s clip in 59s (22M params)
)

# Optional, higher-quality downloadable models (catalog-only until the engine
# layer lands). URL/size/sha256 are real and were verified against the
# HuggingFace API in the reference project (mimrock/musichammer) on 2026-07-05.
#
# LICENSING (load-bearing): BS-RoFormer SW has NO license grant — an anonymous
# author, no terms. redistributable=False means Rend must NEVER bundle or rehost
# this checkpoint. It may only be downloaded on demand from the author's own
# repo, with the license state shown to the user. See downloader.py.
_DOWNLOADABLE_MODELS = (
    Model("bs_roformer_sw", "BS-RoFormer SW (6 stems, best quality)", "bs_roformer",
          ("vocals", "drums", "bass", "guitar", "piano", "other"), "download", karaoke=True,
          description="Highest separation quality (esp. guitar). Large download, "
                      "much slower on CPU than Demucs.",
          files=(ModelFile(
              "BS-Rofo-SW-Fixed.ckpt",
              "https://huggingface.co/enerjazzer/BS-ROFO-SW-Fixed/resolve/main/BS-Rofo-SW-Fixed.ckpt",
              699412152,
              "24e7d35ee9c64415673d3fd33e06a67cac2c103c5df6267ba1576459c775916e",
          ),),
          license="None declared (anonymous author — no license grant)",
          license_url="https://huggingface.co/enerjazzer/BS-ROFO-SW-Fixed",
          redistributable=False),
)

MODELS = _DEMUCS_MODELS + _ROFORMER_MODELS + _DOWNLOADABLE_MODELS
_BY_ID = {m.id: m for m in MODELS}


# ── Lookups ───────────────────────────────────────────────────────────────────

def all_models() -> tuple:
    return MODELS


def get_model(model_id: str):
    """Return the Model with *model_id*, or None."""
    return _BY_ID.get(model_id)


def demucs_models() -> tuple:
    return tuple(m for m in MODELS if m.engine == "demucs")


def downloadable_models() -> tuple:
    return tuple(m for m in MODELS if m.downloadable)


# ── On-disk presence (cheap; hash verification lives in downloader.py) ──────────

def model_file_path(f: ModelFile) -> Path:
    return MODELS_DIR / f.name


def is_installed(model: Model) -> bool:
    """True if every weight file is present with the expected size.

    A size match is a cheap gate, not proof of integrity — downloader.verify()
    does the full sha256 check. Engine-managed models have no Rend-managed
    files, so this is always False for them (the engine owns their weights).
    """
    if not model.downloadable:
        return False
    return all(
        (p := model_file_path(f)).exists() and p.stat().st_size == f.size
        for f in model.files
    )


def files_status(model: Model) -> dict:
    """Summarize how *model*'s weights are provided, for the UI/download layer."""
    return {
        "managed": not model.downloadable,   # engine downloads the weights itself
        "installed": is_installed(model),     # Rend-managed files present on disk
        "redistributable": model.redistributable,
    }
