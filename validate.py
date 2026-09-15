"""Record bounded scenario results and source hashes; never contact GitHub."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CASES = ["clean", "empty", "drop_syn", "drop_syn_ack", "drop_handshake_ack",
         "drop_data", "drop_data_ack", "corrupt_data", "duplicate_data",
         "short_server", "short_client", "small_window", "drop_fin_ack",
         "narrow_buffer", "drop_window_update"]


def measure(case, historical, deadline):
    command = [sys.executable, str(ROOT / "tests" / "scenario.py"), case]
    if historical:
        command.append("--historical")
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=deadline)
        if run.returncode or "Exception in thread" in run.stderr:
            return {"case": case, "outcome": "error", "stderr": run.stderr[-1200:]}
        return {"outcome": "passed", **json.loads(run.stdout)}
    except subprocess.TimeoutExpired as error:
        return {"case": case, "outcome": "deadline_exceeded", "deadline_seconds": deadline,
                "thread_crash_reported": b"Exception in thread" in (error.stderr or b"")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    sources = [ROOT / name for name in ["mrt_client.py", "mrt_server.py", "segment.py", "timer.py",
                                      "tests/scenario.py", "tests/test_transport.py", "validate.py"]]
    sources += sorted((ROOT / "historical").glob("*"))
    report = {"python": platform.python_version(),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources if p.is_file()},
              "prepared": [], "historical": []}
    for repeat in range(args.repeats):
        for case in CASES:
            result = {"repeat": repeat, **measure(case, False, 8)}
            report["prepared"].append(result)
            print(case, result["outcome"], flush=True)
    if args.baseline:
        for case in ["clean", "short_server", "short_client", "small_window", "drop_fin_ack",
                     "drop_data", "drop_window_update"]:
            result = measure(case, True, 4)
            report["historical"].append(result)
            print("historical", case, result["outcome"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return int(any(r["outcome"] != "passed" for r in report["prepared"]))


if __name__ == "__main__":
    raise SystemExit(main())
