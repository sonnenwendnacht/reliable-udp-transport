"""Tests for the preserved protocol, not a replacement transport implementation."""
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

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


class InitializationTests(unittest.TestCase):
    """Fail invalid configuration before starting asynchronous transport work."""

    ENDPOINTS = [
        (Client, "mrt_client", (0, "127.0.0.1", 12345, 128)),
        (Server, "mrt_server", (0, 4096)),
    ]

    def test_client_requires_integer_segment_size(self):
        for size in [128.0, 128.5, "128", None, True, False]:
            with self.subTest(size=size), \
                 patch("mrt_client.socket.socket") as allocate, \
                 patch("mrt_client.open", create=True), \
                 patch("mrt_client.threading.Thread"):
                with self.assertRaises(ValueError):
                    Client().init(0, "127.0.0.1", 12345, size)
                allocate.assert_not_called()

    def test_server_requires_integer_receive_buffer(self):
        for size in [4096.0, 4096.5, "4096", None, True, False]:
            with self.subTest(size=size), \
                 patch("mrt_server.socket.socket") as allocate, \
                 patch("mrt_server.open", create=True), \
                 patch("mrt_server.threading.Thread"):
                with self.assertRaises(ValueError):
                    Server().init(0, size)
                allocate.assert_not_called()

    def test_integer_size_boundaries_still_initialize(self):
        for endpoint_type, module, args in self.ENDPOINTS:
            sizes = [15, 2048] if endpoint_type is Client else [1, 65535]
            for size in sizes:
                with self.subTest(endpoint=module, size=size):
                    endpoint = endpoint_type()
                    sock = Mock()
                    sock.getsockname.return_value = ("127.0.0.1", 54321)
                    log = Mock()
                    with patch(f"{module}.socket.socket", return_value=sock), \
                         patch(f"{module}.open", return_value=log, create=True), \
                         patch(f"{module}.threading.Thread") as worker:
                        endpoint.init(*args[:-1], size)
                    worker.return_value.start.assert_called()
                    sock.close.assert_not_called()
                    log.close.assert_not_called()
                    self.assertEqual(endpoint.src_port, 54321)

    def test_acquisition_failures_close_socket_without_starting_workers(self):
        for endpoint_type, module, args in self.ENDPOINTS:
            for stage in ["bind", "getsockname", "settimeout", "open"]:
                with self.subTest(endpoint=module, stage=stage):
                    sock = Mock()
                    sock.getsockname.return_value = ("127.0.0.1", 54321)
                    failure = OSError(f"injected {stage} failure")
                    if stage != "open":
                        getattr(sock, stage).side_effect = failure
                    with patch(f"{module}.socket.socket", return_value=sock), \
                         patch(f"{module}.open", create=True) as open_log, \
                         patch(f"{module}.threading.Thread") as worker:
                        if stage == "open":
                            open_log.side_effect = failure
                        with self.assertRaises(OSError) as raised:
                            endpoint_type().init(*args)
                    self.assertIs(raised.exception, failure)
                    sock.close.assert_called_once_with()
                    worker.assert_not_called()
                    if stage != "open":
                        open_log.assert_not_called()

    def test_cleanup_error_does_not_replace_initialization_error(self):
        for endpoint_type, module, args in self.ENDPOINTS:
            with self.subTest(endpoint=module):
                sock = Mock()
                sock.getsockname.return_value = ("127.0.0.1", 54321)
                sock.close.side_effect = OSError("injected close failure")
                failure = PermissionError("cannot create log")
                with patch(f"{module}.socket.socket", return_value=sock), \
                     patch(f"{module}.open", side_effect=failure, create=True), \
                     patch(f"{module}.threading.Thread") as worker:
                    with self.assertRaises(PermissionError) as raised:
                        endpoint_type().init(*args)
                self.assertIs(raised.exception, failure)
                sock.close.assert_called_once_with()
                worker.assert_not_called()


CASES = ["clean", "empty", "drop_syn", "drop_syn_ack", "drop_handshake_ack",
         "drop_data", "drop_data_ack", "corrupt_data", "duplicate_data",
         "short_server", "short_client", "small_window", "drop_fin_ack",
         "narrow_buffer", "drop_window_update", "drop_handshake_ack_empty",
         "closed_before_accept"]
for name in CASES:
    setattr(TransportTests, "test_" + name, lambda self, case=name: self.run_case(case))


if __name__ == "__main__":
    unittest.main()
