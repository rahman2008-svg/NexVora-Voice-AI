"""WAV encoding (stdlib only) and reference-audio sniffing."""
import io
import wave

import numpy as np


def to_wav_bytes(samples, sample_rate: int) -> bytes:
    """Encode a mono float waveform in [-1, 1] as 16-bit PCM WAV."""
    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError("empty audio")
    if not np.all(np.isfinite(arr)):
        raise ValueError("audio contains NaN or Inf")
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def sniff_audio(head: bytes) -> bool:
    """Cheap magic-byte check so we don't hand arbitrary files to the model stack."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return True
    if head[:4] in (b"fLaC", b"OggS") or head[:3] == b"ID3":
        return True
    if head[4:8] == b"ftyp":  # m4a / mp4 container
        return True
    return len(head) > 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0  # MPEG frame sync
