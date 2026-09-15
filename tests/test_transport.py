"""Tests for the preserved protocol, not a replacement transport implementation."""
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from segment import Segment


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


CASES = ["clean", "empty", "drop_syn", "drop_syn_ack", "drop_handshake_ack",
         "drop_data", "drop_data_ack", "corrupt_data", "duplicate_data",
         "short_server", "short_client", "small_window", "drop_fin_ack"]
for name in CASES:
    setattr(TransportTests, "test_" + name, lambda self, case=name: self.run_case(case))


if __name__ == "__main__":
    unittest.main()
