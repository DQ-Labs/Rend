"""Headless tests for the Serato DJ .serato-stems export.

The format facts and the ground-truth table come from seven Serato-made files
analysed on Windows; the audio itself is copyrighted and is never fetched or
committed. Everything here runs on synthetic audio. The ffmpeg tests need an
ffmpeg with libmp3lame (and ffprobe), found the way rend_core.ffmpeg_exe()
finds it: PATH first, then the copy in the project root. Skipped without one.
"""

import os
import shutil
import struct
import subprocess
import sys
import threading
import types

import numpy as np
import pytest
import soundfile as sf
import torch

import rend_core
import serato_stems as ss

FRAME = ss.FRAME_SAMPLES


# ── The length rule ───────────────────────────────────────────────────────────

# (original, nb_read_packets, has Info frame, Serato N,
#  ffmpeg default decode, ffmpeg +skip_manual decode)
GROUND_TRUTH = [
    ("A", 7245, True,  8347392, 8345077, 8346240),
    ("B", 9285, True,  10697472, 10695215, 10696320),
    ("C", 9992, False, 11510784, 11510784, 11510784),
    ("D", 3569, True,  4112640, 4110292, 4111488),
    ("E", 4685, False, 5397120, 5397120, 5397120),
    ("F", 6825, False, 7862400, 7862400, 7862400),
    ("G", 7113, True,  8195328, 8192108, 8194176),
]


@pytest.mark.parametrize("name,packets,info,serato_n,default,skip_manual", GROUND_TRUTH)
def test_length_rule_matches_serato(name, packets, info, serato_n, default, skip_manual):
    n = ss.serato_sample_count(packets, info)
    assert n == serato_n
    assert n % FRAME == 0
    # What decode_for_serato relies on: the undelayed decode is packets * 1152,
    # and Serato's N is that plus one frame when there is an Info header.
    assert skip_manual == packets * FRAME
    assert n == skip_manual + (FRAME if info else 0)
    # ffmpeg's default (gapless-trimmed) decode is never the right length when
    # there is an Info frame — the reason the export can't use it.
    if info:
        assert default != n


# ── Container ─────────────────────────────────────────────────────────────────

def test_header_bytes():
    data = ss.pack({i: b"" for i in range(4)}, 1152 * 10)
    assert struct.calcsize(ss.HEADER_FORMAT) == 28
    assert data[:28] == (b"srtshead" + struct.pack(">I", 16) + struct.pack(">HH", 1, 2)
                         + struct.pack(">III", 4, 11520, 44100))
    assert data[:28] == struct.pack(">8sIHHIII", b"srtshead", 16, 1, 2, 4, 11520, 44100)


def test_pack_layout_xor_and_chunk_order():
    mp3s = {0: b"vocals-mp3", 1: b"bass", 2: b"drums!", 3: b"\x00\xff\x26melody"}
    data = ss.pack(mp3s, 1152)
    pos, order = 28, []
    while pos < len(data):
        assert data[pos:pos + 4] == b"stem"
        (length,) = struct.unpack(">I", data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        (index,) = struct.unpack(">I", body[:4])
        assert bytes(b ^ 0x26 for b in body[4:]) == mp3s[index]
        order.append(index)
        pos += 8 + length
    assert order == [1, 2, 3, 0]
    assert pos == len(data)          # nothing after the last chunk


def test_round_trip(tmp_path):
    rng = np.random.default_rng(1)
    mp3s = {i: rng.integers(0, 256, 5000 + i, dtype=np.uint8).tobytes() for i in range(4)}
    path = str(tmp_path / "x.1.2.serato-stems")
    ss.write(path, mp3s, 1152 * 7)
    back = ss.read(path)
    assert back.version == (1, 2)
    assert back.samples == 1152 * 7 and back.rate == 44100
    assert back.stems == mp3s
    assert back.order == [1, 2, 3, 0]
    assert ss.pack(back.stems, back.samples) == open(path, "rb").read()
    assert not os.path.exists(path + ".part")


def test_xor_is_its_own_inverse():
    data = bytes(range(256))
    assert ss.xor(ss.xor(data)) == data
    assert ss.xor(b"\x26") == b"\x00"


def test_pack_rejects_bad_input():
    with pytest.raises(ValueError):
        ss.pack({0: b"", 1: b"", 2: b""}, 1152)               # missing a stem
    with pytest.raises(ValueError):
        ss.pack({i: b"" for i in range(4)}, 1000)             # not a frame multiple


def test_unpack_rejects_garbage():
    with pytest.raises(ValueError):
        ss.unpack(b"RIFF" + b"\0" * 40)
    good = ss.pack({i: b"abc" for i in range(4)}, 1152)
    with pytest.raises(ValueError):
        ss.unpack(good[:-1])                                   # truncated


def test_stems_path_naming():
    assert ss.stems_path(os.path.join("music", "My.Song.mp3")) == \
        os.path.join("music", "My.Song.1.2.serato-stems")


# ── Eligibility ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ["htdemucs", "htdemucs_ft", "mdx", "mdx_extra", "mdx_q"])
def test_four_stem_demucs_models_are_supported(model):
    assert ss.model_problem(model) is None


@pytest.mark.parametrize("model", ["htdemucs_6s", "melband_instrumental", "melband_guitar", "bs_roformer_sw"])
def test_other_models_are_not(model):
    assert ss.model_problem(model)


def test_karaoke_disables_serato():
    assert ss.model_problem("htdemucs", karaoke=True)


def test_supported_models_exist_in_registry_with_the_four_stems():
    import registry
    for model_id in ss.SUPPORTED_MODELS:
        m = registry.get_model(model_id)
        assert m is not None and m.engine == "demucs"
        assert set(m.stems) == set(ss.DEMUCS_TO_SERATO)


def test_source_problem_for_non_mp3(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    assert ss.source_problem(str(wav)) == "Needs an MP3 file"


def _fake_frame(version_bits, rate_idx, kbps_idx=9):
    # 0xFFE sync, version, layer III, no CRC; bitrate, rate, no padding
    b1 = 0xE0 | (version_bits << 3) | (1 << 1) | 1
    b2 = (kbps_idx << 4) | (rate_idx << 2)
    return bytes([0xFF, b1, b2, 0x00])


def test_inspect_mp3_skips_id3_and_reads_frame_header(tmp_path):
    # ID3v2 tag (size 20, syncsafe), then two MPEG-1 L3 44.1k 128 kbps frames
    frame_len = 144000 * 128 // 44100
    frame = _fake_frame(3, 0) + b"\0" * 32 + b"Info" + b"\0" * (frame_len - 40)
    tag = b"ID3\x03\x00\x00" + bytes([0, 0, 0, 20]) + b"\xff\xfb" + b"\0" * 18  # fake sync inside tag
    p = tmp_path / "t.mp3"
    p.write_bytes(tag + frame + _fake_frame(3, 0) + b"\0" * 400)
    info = ss.inspect_mp3(str(p))
    assert info.offset == 30
    assert info.mpeg1_layer3 and info.sample_rate == 44100 and info.has_info_frame
    assert ss.source_problem(str(p)) is None


def test_source_problem_for_48k_and_mpeg2(tmp_path):
    p48 = tmp_path / "48k.mp3"
    frame_len = 144000 * 128 // 48000          # 128 kbps at 48 kHz
    p48.write_bytes((_fake_frame(3, 1) + b"\0" * (frame_len - 4)) * 4)
    assert ss.source_problem(str(p48)) == "Needs a 44.1 kHz MP3"
    p2 = tmp_path / "mpeg2.mp3"
    p2.write_bytes((_fake_frame(2, 0) + b"\0" * 200) * 4)
    assert ss.source_problem(str(p2)) == "Needs an MPEG-1 Layer III MP3"


# ── ffmpeg-backed tests ───────────────────────────────────────────────────────

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool(name):
    """Resolve ffmpeg/ffprobe like rend_core.ffmpeg_exe(): PATH, then the
    project-root copy a source install keeps beside app.py. Without the
    fallback these tests skip silently on a Windows dev checkout."""
    found = shutil.which(name)
    if found:
        return found
    local = os.path.join(_ROOT, name + (".exe" if os.name == "nt" else ""))
    return local if os.path.exists(local) else None


FFMPEG, FFPROBE = _tool("ffmpeg"), _tool("ffprobe")


def _has_lame():
    if not (FFMPEG and FFPROBE):
        return False
    out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                         capture_output=True, text=True).stdout
    return "libmp3lame" in out


needs_lame = pytest.mark.skipif(not _has_lame(), reason="needs ffmpeg + ffprobe with libmp3lame")


def _make_mp3(path, seconds, xing, rate=44100):
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         # noise, not a tone: a periodic signal would make the alignment
         # check below ambiguous
         "-i", f"anoisesrc=sample_rate={rate}:duration={seconds}:amplitude=0.3:seed=7",
         "-ac", "2", "-c:a", "libmp3lame", "-q:a", "2",
         "-write_xing", "1" if xing else "0", str(path)],
        check=True)
    return str(path)


def _packets(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-count_packets", "-select_streams", "a:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    return int(out.strip())


@needs_lame
@pytest.mark.parametrize("xing", [True, False])
def test_info_frame_detection_and_n_on_synthetic_mp3(tmp_path, xing):
    mp3 = _make_mp3(tmp_path / "s.mp3", 3, xing)
    info = ss.inspect_mp3(mp3)
    assert info.mpeg1_layer3 and info.sample_rate == 44100
    assert info.has_info_frame is xing
    audio, n = ss.decode_for_serato(mp3)
    assert n == ss.serato_sample_count(_packets(mp3), xing)
    assert audio.shape == (2, n) and audio.dtype == np.float32
    if xing:
        assert not audio[:, :FRAME].any()      # the Info frame plays as silence


@needs_lame
def test_source_problem_on_real_48k_mp3(tmp_path):
    mp3 = _make_mp3(tmp_path / "s48.mp3", 1, True, rate=48000)
    assert ss.source_problem(mp3) == "Needs a 44.1 kHz MP3"


@needs_lame
def test_encoder_produces_exactly_n_samples(tmp_path):
    n = FRAME * 120
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal((2, n)) * 0.6).astype(np.float32)  # peaks above 1.0
    data = ss.encode_stem(audio, n)
    assert data[0] == 0xFF and (data[1] & 0xE0) == 0xE0           # no ID3, starts at a frame
    mp3 = tmp_path / "e.mp3"
    mp3.write_bytes(data)
    assert ss.decoded_length(str(mp3)) == n
    assert ss.inspect_mp3(str(mp3)).has_info_frame
    # Gapless fields in the LAME/Lavc tag: delay 576, padding 576.
    i = data.find(b"Xing", 0, 64)
    flags = int.from_bytes(data[i + 4:i + 8], "big")
    p = i + 8 + (4 if flags & 1 else 0) + (4 if flags & 2 else 0) \
        + (100 if flags & 4 else 0) + (4 if flags & 8 else 0)
    v = int.from_bytes(data[p + 21:p + 24], "big")
    assert (v >> 12, v & 0xFFF) == (576, 576)


@needs_lame
def test_encode_rejects_wrong_length():
    with pytest.raises(ss.SeratoExportError):
        ss.encode_stem(np.zeros((2, 1000), np.float32), 1152)


# ── End to end, with a stub instead of a Demucs model ────────────────────────

class _StubSeparator:
    """Stands in for demucs.api.Separator: splits the mix into four fixed
    fractions, so the stems sum back to the input."""
    samplerate = 44100
    sources = ("drums", "bass", "other", "vocals")
    weights = {"drums": 0.1, "bass": 0.2, "other": 0.3, "vocals": 0.4}

    def __init__(self, model, device, shifts, progress, callback):
        self.callback = callback
        self.seen = None

    def separate_tensor(self, wav, sr):
        assert sr == 44100 and wav.dtype == torch.float32
        _StubSeparator.last_input = wav.clone()
        self.callback({"state": "end", "segment_offset": wav.shape[1], "audio_length": wav.shape[1]})
        return wav, {s: wav * self.weights[s] for s in self.sources}

    def separate_audio_file(self, path):
        raise AssertionError("Serato export must not use the normal decode")


@pytest.fixture
def stub_demucs(monkeypatch):
    demucs = types.ModuleType("demucs")
    api = types.ModuleType("demucs.api")
    api.Separator = _StubSeparator
    demucs.api = api
    monkeypatch.setitem(sys.modules, "demucs", demucs)
    monkeypatch.setitem(sys.modules, "demucs.api", api)


def _run(input_file, tmp_path, model="htdemucs", fmt=rend_core.SERATO_FORMAT, two_stems=False):
    messages = []
    t = rend_core.SeparationThread(
        input_file=input_file, output_folder=str(tmp_path / "out_stems"),
        model_name=model, shifts=1, two_stems=two_stems,
        callback=lambda msg, frac: messages.append(msg),
        stop_event=threading.Event(), device="cpu", output_format=fmt)
    t.run()
    return t, messages


@needs_lame
@pytest.mark.parametrize("xing", [True, False])
def test_end_to_end_export(tmp_path, stub_demucs, xing):
    mp3 = _make_mp3(tmp_path / "Track One.mp3", 4, xing)
    t, messages = _run(mp3, tmp_path)
    assert messages[-1] == "Done!", messages
    out = tmp_path / "Track One.1.2.serato-stems"
    assert t.serato_file == str(out) and out.is_file()
    assert not (tmp_path / "out_stems").exists()        # no stems folder for Serato

    n = ss.serato_sample_count(_packets(mp3), xing)
    parsed = ss.read(str(out))
    assert parsed.samples == n and parsed.rate == 44100
    assert parsed.order == [1, 2, 3, 0]
    # The separation input was Serato's decode: N samples, silent first frame
    # when there's an Info header.
    assert _StubSeparator.last_input.shape == (2, n)
    if xing:
        assert not _StubSeparator.last_input[:, :FRAME].any()

    # Every stem decodes (from a file) to exactly N, and carries the right
    # share of the mix — so the index mapping is right.
    levels = {}
    for index, data in parsed.stems.items():
        p = tmp_path / f"stem{index}.mp3"
        p.write_bytes(data)
        assert ss.decoded_length(str(p)) == n
        wav = tmp_path / f"stem{index}.wav"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(p), str(wav)], check=True)
        stem = sf.read(str(wav), dtype="float32")[0].T
        levels[index] = float(np.sqrt(np.mean(stem ** 2)))
        if index == ss.VOCALS:
            # Lines up with the separation input at lag 0 — the encode adds no
            # offset — so it lines up with Serato's decode of the original.
            ref = _StubSeparator.last_input.numpy()[0]
            seg = slice(FRAME * 2, FRAME * 2 + 20000)
            lags = range(-1500, 1501)
            corr = [float(np.dot(stem[0][seg], np.roll(ref, lag)[seg])) for lag in lags]
            assert lags[int(np.argmax(corr))] == 0
    ratios = {i: levels[i] / levels[ss.VOCALS] for i in levels}
    assert ratios[ss.BASS] == pytest.approx(0.5, rel=0.05)
    assert ratios[ss.DRUMS] == pytest.approx(0.25, rel=0.05)
    assert ratios[ss.MELODY] == pytest.approx(0.75, rel=0.05)


@needs_lame
def test_end_to_end_refuses_unsupported_choices(tmp_path, stub_demucs):
    mp3 = _make_mp3(tmp_path / "t.mp3", 1, True)
    for kwargs in ({"model": "htdemucs_6s"}, {"two_stems": True}):
        t, messages = _run(mp3, tmp_path, **kwargs)
        assert messages[-1].startswith("Error: Serato DJ export unavailable"), messages
    t, messages = _run(mp3, tmp_path, model="melband_guitar")
    assert messages[-1].startswith("Error: Serato DJ export needs"), messages
    assert not (tmp_path / "t.1.2.serato-stems").exists()


@needs_lame
def test_failed_export_leaves_an_existing_file_alone(tmp_path, stub_demucs, monkeypatch):
    mp3 = _make_mp3(tmp_path / "t.mp3", 1, True)
    existing = tmp_path / "t.1.2.serato-stems"
    existing.write_bytes(b"serato's own file")

    def broken(audio, samples, tmpdir=None):
        raise ss.SeratoExportError("Encoded stem decodes to 1 samples, expected 2")
    monkeypatch.setattr(ss, "encode_stem", broken)
    t, messages = _run(mp3, tmp_path)
    assert messages[-1].startswith("Error: Encoded stem decodes"), messages
    assert existing.read_bytes() == b"serato's own file"


def test_wav_output_unchanged_when_serato_is_off(tmp_path, monkeypatch):
    # The normal path still goes through separate_audio_file + save_stems.
    called = {}

    class Sep(_StubSeparator):
        def separate_audio_file(self, path):
            called["path"] = path
            wav = torch.zeros(2, 100)
            return wav, {s: wav for s in self.sources}

    demucs = types.ModuleType("demucs")
    api = types.ModuleType("demucs.api")
    api.Separator = Sep
    demucs.api = api
    monkeypatch.setitem(sys.modules, "demucs", demucs)
    monkeypatch.setitem(sys.modules, "demucs.api", api)
    song = tmp_path / "s.mp3"
    song.write_bytes(b"")
    t, messages = _run(str(song), tmp_path, fmt="wav")
    assert messages[-1] == "Done!", messages
    assert called["path"] == str(song)
    assert sorted(os.listdir(tmp_path / "out_stems")) == sorted(
        f"{s}.wav" for s in _StubSeparator.sources)
    assert not list(tmp_path.glob("*.serato-stems"))
