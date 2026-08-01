"""Headless tests for the model registry — no torch, no GUI, no network."""

import re

import registry
from registry import (
    Model,
    ModelFile,
    demucs_models,
    download_size,
    downloadable_models,
    files_status,
    format_size,
    get_model,
    is_installed,
    menu_label,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ── Lookups ───────────────────────────────────────────────────────────────────

def test_get_model_returns_known_model():
    m = get_model("htdemucs")
    assert m is not None and m.id == "htdemucs"


def test_get_model_unknown_is_none():
    assert get_model("does_not_exist") is None


def test_all_six_demucs_models_present():
    ids = {m.id for m in demucs_models()}
    assert ids == {"htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx", "mdx_extra", "mdx_q"}


def test_demucs_models_are_engine_managed_not_downloadable():
    for m in demucs_models():
        assert m.engine == "demucs"
        assert m.weights == "engine_managed"
        assert m.downloadable is False
        assert m.files == ()


# ── Stems / karaoke metadata ──────────────────────────────────────────────────

def test_four_stem_models_expose_vocals():
    for mid in ("htdemucs", "mdx", "mdx_extra", "mdx_q"):
        assert "vocals" in get_model(mid).stems


def test_six_stem_model_is_not_karaoke_capable():
    # htdemucs_6s uses different stem naming at runtime and is deliberately
    # excluded from Karaoke Mode. app.py drives its checkbox off this flag, so
    # this is the whole rule, not a copy of one.
    assert get_model("htdemucs_6s").karaoke is False


def test_four_stem_models_are_karaoke_capable():
    assert get_model("htdemucs").karaoke is True


# ── Downloadable models + licensing guardrails ────────────────────────────────

def test_bs_roformer_sw_is_downloadable():
    ids = {m.id for m in downloadable_models()}
    assert "bs_roformer_sw" in ids


def test_downloadable_models_carry_verifiable_file_records():
    for m in downloadable_models():
        assert m.files, f"{m.id} is downloadable but declares no files"
        for f in m.files:
            assert isinstance(f, ModelFile)
            assert f.url.startswith("https://")
            assert f.size > 0
            assert _SHA256_RE.match(f.sha256), f"{f.name} sha256 is not 64 hex chars"


def test_melband_guitar_is_vendored_roformer_download():
    m = get_model("melband_guitar")
    assert m is not None
    assert m.engine == "roformer"             # in-process, vendored architecture
    assert m.downloadable is True             # Rend fetches the checkpoint itself
    assert m.arch_config == "becruily_guitar"
    assert m.stems == ("guitar", "other")
    assert m.redistributable is False         # no license grant — never bundle


def test_melband_instrumental_is_the_karaoke_roformer():
    m = get_model("melband_instrumental")
    assert m is not None
    assert m.engine == "roformer"
    assert m.karaoke is True
    assert m.stems == ("instrumental", "vocals")
    assert m.arch_config == "becruily_instrumental"
    assert m.redistributable is False


def test_roformer_configs_keep_per_checkpoint_quirks():
    # These two checkpoints differ in mlp_expansion_factor: the guitar model needs
    # 1, the instrumental one uses the upstream default. Getting this wrong loads
    # silently wrong weights, so pin the distinction.
    from roformer_source.model_configs import get_config
    assert get_config("becruily_guitar")["model"]["mlp_expansion_factor"] == 1
    assert "mlp_expansion_factor" not in get_config("becruily_instrumental")["model"]


def test_vendored_roformer_models_have_a_known_arch_config():
    # A roformer model without a vendored config would fail only at run time.
    from roformer_source.model_configs import CONFIGS
    for m in registry.all_models():
        if m.engine == "roformer":
            assert m.arch_config in CONFIGS, f"{m.id} references unknown config"


def test_unlicensed_model_is_flagged_non_redistributable():
    # The load-bearing guardrail: a model with no license grant must never be
    # marked redistributable, so Rend can only ever download it on demand.
    sw = get_model("bs_roformer_sw")
    assert sw.redistributable is False
    assert sw.license and sw.license.lower() != "mit"


# ── On-disk presence ──────────────────────────────────────────────────────────

def test_engine_managed_model_is_never_reported_installed():
    # Demucs owns its own weights; the registry manages no files for it.
    assert is_installed(get_model("htdemucs")) is False


def test_is_installed_false_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    assert is_installed(get_model("bs_roformer_sw")) is False


def _tiny_downloadable_model(name="tiny.bin", size=3, sha256="0" * 64):
    """A synthetic downloadable model so presence checks don't touch a 667 MB file."""
    return Model(
        "tiny", "Tiny test model", "roformer", ("vocals", "other"),
        "download", karaoke=True,
        files=(ModelFile(name, "https://example/tiny.bin", size, sha256),),
        redistributable=False,
    )


def test_is_installed_true_when_file_present_with_right_size(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    model = _tiny_downloadable_model(size=3)
    (tmp_path / "tiny.bin").write_bytes(b"abc")  # size matches
    assert is_installed(model) is True


def test_is_installed_false_when_size_mismatches(tmp_path, monkeypatch):
    # A truncated/partial file must not read as installed even if it exists.
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    model = _tiny_downloadable_model(size=3)
    (tmp_path / "tiny.bin").write_bytes(b"ab")  # wrong size
    assert is_installed(model) is False


def test_files_status_shapes_for_both_kinds():
    managed = files_status(get_model("htdemucs"))
    assert managed["managed"] is True and managed["installed"] is False

    dl = files_status(get_model("bs_roformer_sw"))
    assert dl["managed"] is False and dl["redistributable"] is False


# ── Picker labels ─────────────────────────────────────────────────────────────
# app.py keys its label → Model map on these strings and cannot be imported in
# CI (it pulls in customtkinter), so the picker's naming is pinned here.

def test_every_model_has_a_short_name():
    for m in registry.all_models():
        assert m.short_name, f"{m.id} has no short_name for the picker"


def test_short_names_are_unique():
    # Labels are dictionary keys in the picker: a collision would make one
    # model unselectable.
    names = [m.short_name for m in registry.all_models()]
    assert len(names) == len(set(names))


def test_menu_labels_are_unique():
    labels = [menu_label(m) for m in registry.all_models()]
    assert len(labels) == len(set(labels))


def test_menu_label_of_engine_managed_model_is_just_its_name():
    # Demucs fetches its own weights, so there is no Rend download to announce.
    assert menu_label(get_model("htdemucs")) == "Demucs v4"


def test_menu_label_flags_a_pending_download(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    label = menu_label(get_model("melband_instrumental"))
    assert label.startswith("RoFormer Vocals")
    assert "913 MB" in label and "↓" in label


def test_menu_label_drops_the_badge_once_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    model = _tiny_downloadable_model(size=3)
    (tmp_path / "tiny.bin").write_bytes(b"abc")
    assert menu_label(model) == "Tiny test model"   # no short_name → display_name


def test_download_size_sums_every_file():
    assert download_size(get_model("melband_guitar")) == 45142183
    assert download_size(get_model("htdemucs")) == 0   # manages no files


def test_format_size_uses_decimal_mb():
    # Decimal MB matches what HuggingFace reports for these checkpoints.
    assert format_size(913106900) == "913 MB"


# ── Model dataclass basics ────────────────────────────────────────────────────

def test_model_is_frozen():
    m = get_model("htdemucs")
    try:
        m.id = "mutated"
    except Exception as e:
        assert e.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("Model should be immutable (frozen dataclass)")
