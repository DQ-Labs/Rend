"""Headless tests for the verified downloader.

No network: weight "downloads" are served from local files via file:// URLs, so
these exercise the real streaming/hashing/atomic-replace path offline.
"""

import hashlib

import pytest

import downloader
import registry
from downloader import download_file, download_model, is_file_valid, sha256_file, verify
from registry import Model, ModelFile


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _served_file(tmp_path, name="weights.ckpt", data=b"pretend-model-weights"):
    """Write *data* to a source file and return a ModelFile pointing at it via file://."""
    src = tmp_path / "src" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(data)
    return ModelFile(name, src.as_uri(), len(data), _sha256_bytes(data)), data


# ── sha256_file ───────────────────────────────────────────────────────────────

def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"the quick brown fox")
    assert sha256_file(p) == _sha256_bytes(b"the quick brown fox")


# ── download_file happy path ──────────────────────────────────────────────────

def test_download_file_writes_verified_file(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f, data = _served_file(tmp_path)

    dest = download_file(f)

    assert dest == registry.MODELS_DIR / f.name
    assert dest.read_bytes() == data
    assert is_file_valid(f)


def test_download_file_leaves_no_part_file(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f, _ = _served_file(tmp_path)
    download_file(f)
    assert list(registry.MODELS_DIR.glob("*.part")) == []


def test_download_file_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    # Force multiple chunks so progress is called more than once.
    monkeypatch.setattr(downloader, "CHUNK", 8)
    f, data = _served_file(tmp_path, data=b"x" * 40)

    seen = []
    download_file(f, progress=lambda done, total: seen.append((done, total)))

    assert seen[-1] == (len(data), len(data))          # ends at 100%
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)  # monotonic
    assert len(seen) > 1


# ── download_file rejects tampered content ────────────────────────────────────

def test_download_file_rejects_sha256_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f, _ = _served_file(tmp_path, data=b"real-weights")
    # Registry claims a different hash than the served bytes → tampering/corruption.
    lying = ModelFile(f.name, f.url, f.size, _sha256_bytes(b"something-else"))

    with pytest.raises(ValueError, match="sha256 mismatch"):
        download_file(lying)

    # Nothing is left behind: no final file, no .part.
    assert not (registry.MODELS_DIR / f.name).exists()
    assert list(registry.MODELS_DIR.glob("*.part")) == []


# ── download_model orchestration ──────────────────────────────────────────────

def test_download_model_fetches_all_files(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f1, d1 = _served_file(tmp_path, name="a.bin", data=b"aaaa")
    f2, d2 = _served_file(tmp_path, name="b.bin", data=b"bbbbbb")
    model = Model("multi", "Multi-file", "roformer", ("vocals",), "download",
                  karaoke=True, files=(f1, f2), redistributable=False)

    download_model(model)

    assert (registry.MODELS_DIR / "a.bin").read_bytes() == d1
    assert (registry.MODELS_DIR / "b.bin").read_bytes() == d2
    assert verify(model)["verified"] is True


def test_download_model_skips_already_valid_files(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f, data = _served_file(tmp_path, data=b"cached")
    registry.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (registry.MODELS_DIR / f.name).write_bytes(data)  # pre-seed a valid copy

    # Point the record at a broken URL so any actual fetch would fail; the
    # pre-seeded valid file must be skipped, keeping this green.
    broken = ModelFile(f.name, "file:///no/such/path.bin", f.size, f.sha256)
    model = Model("one", "One", "roformer", ("vocals",), "download",
                  karaoke=True, files=(broken,), redistributable=False)

    download_model(model)  # must not raise — the valid file is skipped
    assert (registry.MODELS_DIR / f.name).read_bytes() == data


def test_download_model_progress_spans_whole_model(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f1, _ = _served_file(tmp_path, name="a.bin", data=b"aaaa")     # 4 bytes
    f2, _ = _served_file(tmp_path, name="b.bin", data=b"bbbbbb")   # 6 bytes
    model = Model("multi", "Multi", "roformer", ("vocals",), "download",
                  karaoke=True, files=(f1, f2), redistributable=False)

    seen = []
    download_model(model, progress=lambda done, total: seen.append((done, total)))

    assert seen[-1] == (10, 10)                    # total across both files
    assert all(total == 10 for _, total in seen)   # one continuous bar


# ── verify() ──────────────────────────────────────────────────────────────────

def test_verify_engine_managed_model_is_none():
    assert verify(registry.get_model("htdemucs"))["verified"] is None


def test_verify_detects_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "models")
    f, _ = _served_file(tmp_path)
    model = Model("one", "One", "roformer", ("vocals",), "download",
                  karaoke=True, files=(f,), redistributable=False)
    assert verify(model)["verified"] is False  # nothing downloaded yet


def test_download_model_rejects_engine_managed():
    with pytest.raises(ValueError, match="no Rend-managed weights"):
        download_model(registry.get_model("htdemucs"))
