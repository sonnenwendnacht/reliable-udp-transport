"""Bounded localhost scenarios; run in a subprocess so protocol hangs are contained."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import os

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("case")
parser.add_argument("--historical", action="store_true")
parser.add_argument("--diagnostic", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "historical" if args.historical else ROOT))
from mrt_client import Client
from mrt_server import Server
from segment import Segment


class Proxy:
    def __init__(self, server, case):
        self.server = server
        self.case = case
        self.client = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.injected = 0
        self.fin_seen = False
        self.data_packets = 0
        self.zero_window_seen = False
        self.worker = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while self.running:
            try:
                raw, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            from_server = addr == self.server
            if not from_server:
                self.client = addr
            target = self.client if from_server else self.server
            seg = Segment.deserialize(raw)
            if not from_server and seg.flags == Segment.FIN:
                self.fin_seen = True
            if not from_server and seg.flags == Segment.DAT:
                self.data_packets += 1
            if from_server and seg.flags == Segment.ACK and seg.window == 0 and seg.ack_num > 0:
                self.zero_window_seen = True
            matches = {
                "drop_syn": not from_server and seg.flags == Segment.SYN,
                "drop_syn_ack": from_server and seg.flags == (Segment.SYN | Segment.ACK),
                "drop_handshake_ack": not from_server and seg.flags == Segment.ACK,
                "drop_data": not from_server and seg.flags == Segment.DAT,
                "drop_data_ack": from_server and seg.flags == Segment.ACK and seg.ack_num > 0,
                "drop_fin_ack": from_server and self.fin_seen and seg.flags == Segment.ACK,
                "corrupt_data": not from_server and seg.flags == Segment.DAT,
                "duplicate_data": not from_server and seg.flags == Segment.DAT,
                "short_server": not from_server and seg.flags == Segment.SYN,
                "short_client": from_server and seg.flags == (Segment.SYN | Segment.ACK),
                "drop_window_update": from_server and self.zero_window_seen and seg.flags == Segment.ACK and seg.window > 0,
            }
            if not self.injected and matches.get(self.case, False):
                self.injected += 1
                if self.case.startswith("drop_"):
                    continue
                if self.case == "corrupt_data":
                    raw = raw[:-1] + bytes([raw[-1] ^ 1])
                elif self.case == "duplicate_data":
                    self.sock.sendto(raw, target)
                elif self.case.startswith("short_"):
                    self.sock.sendto(b"short", target)
                    time.sleep(0.1)
            self.sock.sendto(raw, target)


def run():
    payload = bytes((i * 31) % 256 for i in range(8024))
    if args.case == "small_window":
        payload = b"hello"
    if args.case == "empty":
        payload = b""
    server = Server()
    window = 32 if args.case in {"small_window", "narrow_buffer"} else 4096
    if args.case == "drop_window_update":
        window = 114
    server.init(0, window)
    server_addr = ("127.0.0.1", server.sock.getsockname()[1])
    proxy = Proxy(server_addr, args.case)
    proxy.worker.start()
    client = Client()
    # Different ephemeral ports avoid fixed port conflicts; logs are disposable.
    client.init(0, "127.0.0.1", proxy.port, 128)
    received = []

    if args.diagnostic:
        def diagnostic():
            while client.running:
                time.sleep(2)
                print(json.dumps({"client_state": client.state,
                                  "server_state": server.state,
                                  "sent": client.seq_num,
                                  "acked": client.base_seq_num,
                                  "expected": server.expected_seq,
                                  "window": client.send_window_size,
                                  "unacked": len(client.unacked_segments),
                                  "injected": proxy.injected}), file=sys.stderr, flush=True)
        threading.Thread(target=diagnostic, daemon=True).start()

    def receiver():
        conn = server.accept()
        if args.case == "drop_window_update":
            time.sleep(0.15)
        received.append(server.receive(conn, len(payload)))

    reader = threading.Thread(target=receiver, daemon=True)
    reader.start()
    started = time.monotonic()
    client.connect()
    client.send(payload)
    reader.join(2)
    assert not reader.is_alive(), "receiver did not finish"
    assert received == [payload], "payload differs"
    client.close()
    server.close()
    proxy.running = False
    proxy.worker.join(1)
    proxy.sock.close()
    # Historical close() does not close sockets; keep the harness leak-free.
    client.sock.close()
    server.sock.close()
    if args.case not in {"clean", "empty", "small_window", "narrow_buffer"}:
        assert proxy.injected == 1, "requested fault was not exercised"
    return {
        "case": args.case,
        "source": "historical" if args.historical else "prepared",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "faults_injected": proxy.injected,
        "data_packets": proxy.data_packets,
        "seconds": round(time.monotonic() - started, 3),
        "correct": True,
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="udp-scenario-") as directory:
        os.chdir(directory)
        print(json.dumps(run()), flush=True)
