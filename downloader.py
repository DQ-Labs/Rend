"""SHA256-verified downloader for Rend-managed model weights.

Weights are fetched from the model author's ORIGINAL repository — Rend never
rehosts them (several optional models carry no redistribution grant; see
registry.py). Every file is streamed to a ``.part`` sidecar, hashed as it
arrives, and only promoted to its final name via an atomic ``replace()`` once
the sha256 matches the registry. A mismatch deletes the partial file and
raises, so a corrupt or tampered download can never be left in place.

No torch, no GUI — pure stdlib + the registry records — so it stays cheap to
import and is fully testable headlessly (tests/test_downloader.py).

The verify/download logic is adapted from the reference project
mimrock/musichammer (MIT), reworked into synchronous functions with an optional
progress callback; threading/UI state is left to the caller.
"""

import hashlib
import urllib.request
from pathlib import Path

import config
import registry

CHUNK = 1024 * 1024  # 1 MiB streaming/hashing block


def sha256_file(path) -> str:
    """Return the lowercase hex sha256 of *path*, read in CHUNK-sized blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def is_file_valid(f: registry.ModelFile) -> bool:
    """True if the on-disk copy of *f* exists and matches its size and sha256."""
    path = registry.model_file_path(f)
    return path.exists() and path.stat().st_size == f.size and sha256_file(path) == f.sha256


def verify(model: registry.Model) -> dict:
    """Full sha256 check of every weight file of a downloadable *model*.

    Returns {"verified": bool, "files": {name: bool}}. For engine-managed
    models (no Rend-managed files) returns {"verified": None, ...}.
    """
    if not model.downloadable:
        return {"verified": None, "files": {}, "detail": "weights are managed by the engine"}
    results = {f.name: is_file_valid(f) for f in model.files}
    return {"verified": all(results.values()), "files": results}


def download_file(f: registry.ModelFile, progress=None, should_stop=None) -> Path:
    """Download one ModelFile into MODELS_DIR, verifying its sha256.

    *progress*, if given, is called as progress(bytes_done, total_bytes) as the
    file streams in. *should_stop*, if given, is polled once per block and
    raises KeyboardInterrupt when it returns True — the same signal the rest of
    the cancel path uses. Returns the final path. Raises ValueError on a sha256
    mismatch (after removing the partial file); the destination is left
    untouched in that case.
    """
    dest = registry.model_file_path(f)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")

    h = hashlib.sha256()
    fetched = 0
    cancelled = False
    req = urllib.request.Request(
        f.url, headers={"User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}"}
    )
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
        while block := r.read(CHUNK):
            # Checked per block rather than per file: these checkpoints run to
            # 913 MB, and without this a cancel did nothing at all until the
            # whole download finished.
            if should_stop is not None and should_stop():
                cancelled = True
                break
            out.write(block)
            h.update(block)
            fetched += len(block)
            if progress:
                progress(fetched, f.size)

    if cancelled:
        part.unlink(missing_ok=True)   # no resume, so a partial is dead weight
        raise KeyboardInterrupt

    digest = h.hexdigest()
    if digest != f.sha256:
        part.unlink(missing_ok=True)
        raise ValueError(
            f"sha256 mismatch for {f.name}: expected {f.sha256}, got {digest} "
            "— refusing to keep the file"
        )
    part.replace(dest)
    return dest


def download_model(model: registry.Model, progress=None, should_stop=None) -> None:
    """Download every missing/invalid weight file of *model*.

    Files already present and valid are skipped (the download is resumable at
    file granularity). *progress* is called as progress(bytes_done, total_bytes)
    across the whole model, so a multi-file model reports one continuous bar.
    *should_stop* is forwarded to each file so a cancel is honoured mid-stream.
    """
    if not model.downloadable:
        raise ValueError(f"model {model.id!r} has no Rend-managed weights to download")

    total = sum(f.size for f in model.files)
    done_before = 0
    for f in model.files:
        if is_file_valid(f):
            done_before += f.size
            if progress and total:
                progress(done_before, total)
            continue

        base = done_before  # freeze for this file's closure

        def file_progress(fetched, _size, _base=base):
            if progress and total:
                progress(_base + fetched, total)

        download_file(f, progress=file_progress, should_stop=should_stop)
        done_before += f.size
