"""Framework-free tests (stdlib unittest; also collected by pytest)."""
import io
import os
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from app.audio import sniff_audio, to_wav_bytes
from app.config import load_settings
from app.model_service import ModelService, ModelUnavailable
from app.options import build_instruct
from app.ratelimit import SlidingWindowLimiter
from app.storage import cleanup_dir, new_temp_path


class TestOptions(unittest.TestCase):
    def test_build_instruct_order_and_skips(self):
        got = build_instruct({"accent": "British Accent", "gender": "female", "age": "auto", "pitch": ""})
        self.assertEqual(got, "female, british accent")

    def test_empty_is_none(self):
        self.assertIsNone(build_instruct({}))

    def test_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            build_instruct({"gender": "robot"})

    def test_rejects_injection_and_unknown_key(self):
        with self.assertRaises(ValueError):
            build_instruct({"gender": "male, whisper"})
        with self.assertRaises(ValueError):
            build_instruct({"hack": "x"})


class TestAudio(unittest.TestCase):
    def test_wav_roundtrip(self):
        t = np.linspace(0, 1, 24000, endpoint=False)
        data = to_wav_bytes(0.5 * np.sin(2 * np.pi * 440 * t), 24000)
        with wave.open(io.BytesIO(data)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
            self.assertEqual(w.getnframes(), 24000)

    def test_rejects_bad_audio(self):
        with self.assertRaises(ValueError):
            to_wav_bytes([], 24000)
        with self.assertRaises(ValueError):
            to_wav_bytes([0.0, float("nan")], 24000)

    def test_sniff(self):
        self.assertTrue(sniff_audio(b"RIFF\x00\x00\x00\x00WAVEfmt "))
        self.assertTrue(sniff_audio(b"ID3\x04" + b"\x00" * 12))
        self.assertFalse(sniff_audio(b"MZ\x90\x00" + b"\x00" * 12))


class TestRateLimit(unittest.TestCase):
    def test_blocks_then_recovers(self):
        lim = SlidingWindowLimiter(2, 60)
        self.assertTrue(lim.check("a", now=0)[0])
        self.assertTrue(lim.check("a", now=1)[0])
        ok, retry = lim.check("a", now=2)
        self.assertFalse(ok)
        self.assertGreaterEqual(retry, 1)
        self.assertTrue(lim.check("b", now=2)[0])      # other clients unaffected
        self.assertTrue(lim.check("a", now=61)[0])     # window passed


class TestStorage(unittest.TestCase):
    def test_cleanup_only_removes_own_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mine = new_temp_path(d, ".wav")
            mine.write_bytes(b"x")
            other = d / "important.txt"
            other.write_text("keep me")
            old = time.time() - 1000
            os.utime(mine, (old, old))
            os.utime(other, (old, old))
            self.assertEqual(cleanup_dir(d, 300), 1)
            self.assertFalse(mine.exists())
            self.assertTrue(other.exists())


class TestConfigAndService(unittest.TestCase):
    def test_defaults_are_safe(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            s = load_settings()
        self.assertFalse(s.enable_voice_cloning)
        self.assertFalse(s.allow_cpu)
        self.assertFalse(s.trust_proxy)

    def test_bad_numbers_fall_back(self):
        with mock.patch.dict(os.environ, {"MAX_TEXT_CHARS": "abc", "MAX_QUEUE": "9999"}, clear=True):
            s = load_settings()
        self.assertEqual(s.max_text_chars, 1000)
        self.assertEqual(s.max_queue, 50)

    def test_unavailable_when_stack_missing(self):
        """Without torch/omnivoice installed the service must say so, never fake audio."""
        svc = ModelService(load_settings())
        with mock.patch.dict("sys.modules", {"torch": None, "omnivoice": None}):
            svc.load()
            self.assertEqual(svc.status()["state"], "unavailable")
            with self.assertRaises(ModelUnavailable):
                svc.generate("hello")


if __name__ == "__main__":
    unittest.main()
