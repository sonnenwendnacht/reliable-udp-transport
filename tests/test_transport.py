"""Tests for the preserved protocol, not a replacement transport implementation."""
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from segment import Segment
from mrt_client import Client
from mrt_server import Server
from timer import Timer


class SegmentTests(unittest.TestCase):
    def test_round_trip_and_independent_checksum(self):
        rng = random.Random(4119)
        for size in [0, 1, 2, 3, 100, 113, 2034]:
            with self.subTest(size=size):
                data = rng.randbytes(size)
                packet = Segment(seq_num=31, ack_num=17, flags=Segment.DAT,
                                 window=4096, data=data).serialize()
                words = packet + (b"\x00" if len(packet) % 2 else b"")
                total = sum(struct.unpack("!" + "H" * (len(words) // 2), words))
                while total >> 16:
                    total = (total & 0xffff) + (total >> 16)
                self.assertEqual(total, 0xffff)
                parsed = Segment.deserialize(packet)
                self.assertEqual((parsed.seq_num, parsed.ack_num, parsed.flags,
                                  parsed.window, parsed.data),
                                 (31, 17, Segment.DAT, 4096, data))
                self.assertFalse(parsed.is_corrupt())

    def test_detect_single_bit_corruption(self):
        original = Segment(seq_num=17, flags=Segment.DAT, data=b"payload").serialize()
        for byte_index in range(len(original)):
            for bit in range(8):
                raw = bytearray(original)
                raw[byte_index] ^= 1 << bit
                self.assertTrue(Segment.deserialize(raw).is_corrupt())


class TransportTests(unittest.TestCase):
    def run_case(self, name):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "scenario.py"), name],
            capture_output=True, text=True, timeout=8,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Exception in thread", result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["correct"])

    def test_invalid_segment_sizes(self):
        for size in [-1, 0, 14, 2049]:
            with self.assertRaises(ValueError):
                Client().init(0, "127.0.0.1", 12345, size)

    def test_invalid_receive_buffer(self):
        for size in [-1, 0, 65536]:
            with self.assertRaises(ValueError):
                Server().init(0, size)

    def test_monotonic_timer(self):
        timer = Timer(0.5)
        self.assertFalse(timer.timeout())
        with patch("timer.time.monotonic", side_effect=[100, 100.49, 100.51]):
            timer.start()
            self.assertFalse(timer.timeout())
            self.assertTrue(timer.timeout())
        timer.stop()
        self.assertFalse(timer.timeout())


CASES = ["clean", "empty", "drop_syn", "drop_syn_ack", "drop_handshake_ack",
         "drop_data", "drop_data_ack", "corrupt_data", "duplicate_data",
         "short_server", "short_client", "small_window", "drop_fin_ack",
         "narrow_buffer", "drop_window_update", "drop_handshake_ack_empty",
         "closed_before_accept"]
for name in CASES:
    setattr(TransportTests, "test_" + name, lambda self, case=name: self.run_case(case))


if __name__ == "__main__":
    unittest.main()
