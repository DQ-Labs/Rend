"""Serato DJ `.serato-stems` export.

Serato DJ Pro keeps the stems it computes for a track in a file next to that
track, `<basename>.1.2.serato-stems`. Writing that file ourselves makes Serato
play Rend's separation as its own native stems. Serato publishes no spec; the
layout below was reverse engineered from Serato-made files (a reader/writer
built from it repacks them byte-identical) and a file Serato did not make was
loaded and played by Serato DJ Pro.

File layout (big-endian):

    header  b"srtshead", u32 16 (header body length), u16 1, u16 2 (version
            1.2), u32 4 (stem count), u32 N (samples per channel, a multiple
            of 1152), u32 44100 (sample rate)
    4 x     b"stem", u32 body length, body = u32 stem index + the stem's
            complete MP3 file with every byte XOR 0x26

Chunks are written in index order 1, 2, 3, 0; nothing follows the last. The
XOR is an obfuscation layer, undone here only for interoperability.

The length rule is what makes Serato accept or reject a file: if the stems'
length doesn't match Serato's own decode of the original, Serato moves the
stems file to the Recycle Bin. For an MP3 original Serato counts

    N = (audio frames + 1 if the first frame is a Xing/Info header) * 1152

— it plays the header frame as 1152 samples of silence and does no gapless
trimming. ffmpeg's `-flags2 +skip_manual` decode gives exactly audio frames *
1152 (no gapless trimming; the Info frame is consumed as a header), so the
separation input is that decode with 1152 samples of silence prepended when
the original has an Info frame: exactly N samples, aligned with what Serato
plays.

This module imports no GUI code and no torch: it works on numpy arrays, so it
is testable headlessly. ffmpeg comes from rend_core.ffmpeg_exe() (imported
lazily — rend_core imports this module), never a hardcoded path.
"""

import os
import struct
import subprocess
import tempfile
from collections import namedtuple

import numpy as np
import soundfile as sf

# ── Format constants ──────────────────────────────────────────────────────────

HEADER_MAGIC = b"srtshead"
CHUNK_MAGIC = b"stem"
HEADER_FORMAT = ">8sIHHIII"          # magic, body len, ver major, ver minor, stems, N, rate
HEADER_BODY_LEN = 16
VERSION = (1, 2)
STEM_COUNT = 4
XOR_KEY = 0x26
FRAME_SAMPLES = 1152                 # samples per MPEG-1 Layer III frame
SAMPLE_RATE = 44100
FILE_SUFFIX = ".1.2.serato-stems"

# Serato's stem indices, and the order chunks are written in.
VOCALS, BASS, DRUMS, MELODY = 0, 1, 2, 3
CHUNK_ORDER = (BASS, DRUMS, MELODY, VOCALS)
STEM_NAMES = {VOCALS: "vocals", BASS: "bass", DRUMS: "drums", MELODY: "melody"}

# Demucs 4-stem output → Serato index. Demucs' "other" is Serato's melody.
DEMUCS_TO_SERATO = {"vocals": VOCALS, "bass": BASS, "drums": DRUMS, "other": MELODY}

# The Demucs models whose output is exactly drums/bass/other/vocals. Decided:
# Demucs only — not htdemucs_6s (six stems) and not the RoFormer models.
SUPPORTED_MODELS = ("htdemucs", "htdemucs_ft", "mdx", "mdx_extra", "mdx_q")

# What every stem's MP3 must be: stereo 44.1 kHz LAME VBR, no ID3 tags, with a
# Xing header carrying gapless delay 576 / padding 576. Given exactly N input
# samples (N a multiple of 1152) ffmpeg's libmp3lame produces exactly that.
ENCODE_ARGS = ["-c:a", "libmp3lame", "-q:a", "0", "-cutoff", "22100",
               "-id3v2_version", "0", "-write_id3v1", "0", "-write_xing", "1"]

_XOR_TABLE = bytes(b ^ XOR_KEY for b in range(256))


class SeratoExportError(RuntimeError):
    """The export can't produce a file Serato would accept, so none is written."""


def xor(data):
    """XOR every byte with 0x26 (its own inverse)."""
    return bytes(data).translate(_XOR_TABLE)


def stems_path(original_path):
    """Where Serato looks for *original_path*'s stems: same folder, same basename."""
    return os.path.splitext(original_path)[0] + FILE_SUFFIX


def serato_sample_count(audio_frames, has_info_frame):
    """Serato's sample count N for an MP3 original.

    *audio_frames* is what `ffprobe -count_packets` reports as nb_read_packets
    (it excludes the Info frame). Serato plays the Info frame as one frame of
    silence and trims nothing.
    """
    return (audio_frames + (1 if has_info_frame else 0)) * FRAME_SAMPLES


# ── Container: pack / unpack ──────────────────────────────────────────────────

SeratoStems = namedtuple("SeratoStems", "version samples rate stems order")


def pack(stems, samples, rate=SAMPLE_RATE):
    """Serialize {index: mp3 bytes} into .serato-stems bytes."""
    if set(stems) != set(CHUNK_ORDER):
        raise ValueError(f"Need exactly stems {sorted(CHUNK_ORDER)}, got {sorted(stems)}")
    if samples <= 0 or samples % FRAME_SAMPLES:
        raise ValueError(f"Sample count {samples} is not a positive multiple of {FRAME_SAMPLES}")
    out = [struct.pack(HEADER_FORMAT, HEADER_MAGIC, HEADER_BODY_LEN, *VERSION,
                       STEM_COUNT, samples, rate)]
    for index in CHUNK_ORDER:
        body = struct.pack(">I", index) + xor(stems[index])
        out.append(CHUNK_MAGIC + struct.pack(">I", len(body)) + body)
    return b"".join(out)


def unpack(data):
    """Parse .serato-stems bytes. Returns SeratoStems(version, samples, rate,
    stems={index: mp3 bytes}, order=[index as written]). Raises ValueError on
    anything malformed."""
    hdr_len = struct.calcsize(HEADER_FORMAT)
    if len(data) < hdr_len:
        raise ValueError("File too short for a .serato-stems header")
    magic, body_len, major, minor, count, samples, rate = struct.unpack_from(HEADER_FORMAT, data)
    if magic != HEADER_MAGIC or body_len != HEADER_BODY_LEN:
        raise ValueError("Not a .serato-stems file (bad header)")
    pos, stems, order = hdr_len, {}, []
    while pos < len(data):
        if data[pos:pos + 4] != CHUNK_MAGIC or pos + 8 > len(data):
            raise ValueError(f"Bad stem chunk at offset {pos}")
        (length,) = struct.unpack_from(">I", data, pos + 4)
        body = data[pos + 8:pos + 8 + length]
        if length < 4 or len(body) != length:
            raise ValueError(f"Truncated stem chunk at offset {pos}")
        (index,) = struct.unpack_from(">I", body)
        if index in stems:
            raise ValueError(f"Duplicate stem index {index}")
        stems[index] = xor(body[4:])
        order.append(index)
        pos += 8 + length
    if len(stems) != count:
        raise ValueError(f"Header says {count} stems, file has {len(stems)}")
    return SeratoStems((major, minor), samples, rate, stems, order)


def read(path):
    with open(path, "rb") as f:
        return unpack(f.read())


def write(path, stems, samples, rate=SAMPLE_RATE):
    """Write {index: mp3 bytes} to *path* atomically.

    The bytes go to a temp file that is read back and parsed before it replaces
    *path*, so a failure never leaves a half-written file where Serato looks —
    and never destroys a stems file that was already there.
    """
    data = pack(stems, samples, rate)
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        with open(part, "rb") as f:
            check = unpack(f.read())
        if check.samples != samples or check.stems != dict(stems):
            raise SeratoExportError("Serato stems file failed read-back verification")
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)


# ── MP3 inspection ────────────────────────────────────────────────────────────

# MPEG-1 Layer III bitrates (kbps) by index; MPEG-1 sample rates by index.
_MPEG1_L3_KBPS = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None)
_MPEG1_RATES = (44100, 48000, 32000, None)

Mp3Info = namedtuple("Mp3Info", "offset mpeg1_layer3 sample_rate has_info_frame")


def _id3v2_size(data):
    """Bytes taken by a leading ID3v2 tag (0 if none)."""
    if len(data) >= 10 and data[:3] == b"ID3":
        size = 0
        for b in data[6:10]:
            size = (size << 7) | (b & 0x7F)        # syncsafe integer
        footer = 10 if data[5] & 0x10 else 0
        return 10 + size + footer
    return 0


def _frame_header(data, pos):
    """Decode the 4-byte MPEG audio header at *pos*. Returns (mpeg1_layer3,
    sample_rate, frame_length) or None if it isn't a plausible header."""
    if pos + 4 > len(data):
        return None
    b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
    if data[pos] != 0xFF or (b1 & 0xE0) != 0xE0:
        return None
    version = (b1 >> 3) & 0x03          # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5, 1 = reserved
    layer = (b1 >> 1) & 0x03            # 1 = Layer III
    bitrate_idx = b2 >> 4
    rate_idx = (b2 >> 2) & 0x03
    padding = (b2 >> 1) & 0x01
    if version == 1 or layer == 0 or bitrate_idx in (0, 15) or rate_idx == 3 or (b3 & 0x03) == 2:
        return None
    mpeg1_l3 = version == 3 and layer == 1
    rate = {3: 1, 2: 2, 0: 4}[version]
    sample_rate = _MPEG1_RATES[rate_idx] // rate
    if mpeg1_l3:
        length = 144000 * _MPEG1_L3_KBPS[bitrate_idx] // sample_rate + padding
    else:
        # Not an MPEG-1 Layer III frame: still a valid sync, but Rend doesn't
        # export these, so the exact length only matters for the sanity check.
        length = 0
    return mpeg1_l3, sample_rate, length


def inspect_mp3(path):
    """Find the first MPEG frame after any ID3v2 tag and report what it is.

    has_info_frame is True when that frame carries a Xing or Info header. A
    candidate sync is accepted only if another frame header follows it where
    its length says, so stray 0xFFE bytes in junk data aren't mistaken for it.
    Raises ValueError if no frame is found.
    """
    with open(path, "rb") as f:
        head = f.read(10)
        skip = _id3v2_size(head)
        f.seek(skip)
        data = f.read(256 * 1024)
    pos = 0
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 4 > len(data):
            raise ValueError("No MPEG audio frame found")
        hdr = _frame_header(data, pos)
        if hdr:
            mpeg1_l3, rate, length = hdr
            if not mpeg1_l3:
                return Mp3Info(skip + pos, False, rate, False)
            if _frame_header(data, pos + length) or pos + length >= len(data):
                frame = data[pos:pos + length]
                has_info = b"Xing" in frame or b"Info" in frame
                return Mp3Info(skip + pos, True, rate, has_info)
        pos += 1


# ── Eligibility ───────────────────────────────────────────────────────────────

def model_problem(model_id, karaoke=False):
    """Why the Serato export can't run with this model/Karaoke setting, or None."""
    if karaoke:
        return "Turn off Karaoke Mode"
    if model_id not in SUPPORTED_MODELS:
        return "Needs a 4-stem Demucs model"
    return None


def source_problem(path):
    """Why *path* can't be exported for Serato, or None if it can."""
    if os.path.splitext(path)[1].lower() != ".mp3":
        return "Needs an MP3 file"
    try:
        info = inspect_mp3(path)
    except (OSError, ValueError):
        return "Can't read this MP3"
    if not info.mpeg1_layer3:
        return "Needs an MPEG-1 Layer III MP3"
    if info.sample_rate != SAMPLE_RATE:
        return "Needs a 44.1 kHz MP3"
    return None


# ── ffmpeg ────────────────────────────────────────────────────────────────────

def _ffmpeg():
    from rend_core import ffmpeg_exe     # deferred: rend_core imports this module
    return ffmpeg_exe()


def _run_ffmpeg(args):
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-nostdin", "-y", *args],
                          capture_output=True, creationflags=creationflags)
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SeratoExportError(f"ffmpeg failed: {msg[-1] if msg else proc.returncode}")


def decode_for_serato(path, tmpdir=None):
    """Decode *path* the way Serato does. Returns (audio float32 (2, N), N).

    `+skip_manual` turns off ffmpeg's gapless trimming, giving audio frames *
    1152 samples; one frame of silence is prepended when the original has an
    Info frame. The result is exactly serato_sample_count() samples and lines
    up with what Serato plays.
    """
    info = inspect_mp3(path)
    with tempfile.TemporaryDirectory(dir=tmpdir) as td:
        wav = os.path.join(td, "decoded.wav")
        _run_ffmpeg(["-flags2", "+skip_manual", "-i", path,
                     "-ac", "2", "-c:a", "pcm_f32le", wav])
        data, rate = sf.read(wav, dtype="float32", always_2d=True)   # (frames, ch)
    if rate != SAMPLE_RATE:
        raise SeratoExportError(f"Decoded at {rate} Hz, expected {SAMPLE_RATE}")
    decoded = data.shape[0]
    if decoded % FRAME_SAMPLES:
        raise SeratoExportError(
            f"Undelayed decode is {decoded} samples, not a whole number of frames")
    n = serato_sample_count(decoded // FRAME_SAMPLES, info.has_info_frame)
    audio = data.T
    if info.has_info_frame:
        audio = np.concatenate([np.zeros((2, FRAME_SAMPLES), np.float32), audio], axis=1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    assert audio.shape[1] == n
    return audio, n


def decoded_length(mp3_path, tmpdir=None):
    """Samples ffmpeg decodes from *mp3_path* with its normal (gapless) decode.

    Decoded from the file, never stdin: reading from a pipe can defeat the
    gapless trimming this check depends on.
    """
    with tempfile.TemporaryDirectory(dir=tmpdir) as td:
        wav = os.path.join(td, "check.wav")
        _run_ffmpeg(["-i", mp3_path, "-c:a", "pcm_s16le", wav])
        return sf.info(wav).frames


def encode_stem(audio, samples, tmpdir=None):
    """Encode a (2, samples) float array to Serato's stem MP3 and verify it.

    Fed as float WAV so nothing is hard-clipped before LAME. The encoded file
    is decoded back from disk and must come back to exactly *samples*;
    otherwise this raises rather than hand Serato a file it would trash.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if audio.shape != (2, samples):
        raise SeratoExportError(f"Stem is {audio.shape}, expected (2, {samples})")
    with tempfile.TemporaryDirectory(dir=tmpdir) as td:
        wav = os.path.join(td, "stem.wav")
        mp3 = os.path.join(td, "stem.mp3")
        sf.write(wav, audio.T, SAMPLE_RATE, format="WAV", subtype="FLOAT")
        _run_ffmpeg(["-i", wav, *ENCODE_ARGS, mp3])
        got = decoded_length(mp3, td)
        if got != samples:
            raise SeratoExportError(
                f"Encoded stem decodes to {got} samples, expected {samples}")
        with open(mp3, "rb") as f:
            data = f.read()
    if _frame_header(data, 0) is None:
        raise SeratoExportError("Encoded stem does not start with an MPEG frame")
    return data


def export(original_path, stems, samples, progress=None, should_stop=None):
    """Encode four Demucs stems and write `<original>.1.2.serato-stems`.

    *stems* maps Demucs names (vocals/bass/drums/other) to (2, samples) float
    arrays; *samples* is the N from decode_for_serato(). *progress(done, total)*
    is called after each stem; *should_stop()* is checked between stems and
    raises KeyboardInterrupt. Returns the written path.
    """
    missing = set(DEMUCS_TO_SERATO) - set(stems)
    if missing:
        raise SeratoExportError(f"Missing stems for Serato: {sorted(missing)}")
    encoded = {}
    for done, (name, index) in enumerate(DEMUCS_TO_SERATO.items(), 1):
        if should_stop and should_stop():
            raise KeyboardInterrupt
        encoded[index] = encode_stem(stems[name], samples)
        if progress:
            progress(done, len(DEMUCS_TO_SERATO))
    if should_stop and should_stop():
        raise KeyboardInterrupt
    out = stems_path(original_path)
    write(out, encoded, samples)
    return out
