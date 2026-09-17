# Reliable UDP transport study

[![Tests](https://github.com/sonnenwendnacht/reliable-udp-transport/actions/workflows/tests.yml/badge.svg)](https://github.com/sonnenwendnacht/reliable-udp-transport/actions/workflows/tests.yml)

A Python transport over UDP, developed for Junzhe Zong's CSEE 4119 Spring 2026
assignment 2 and maintained with deterministic packet-fault tests. The original
implementation and assignment write-ups are preserved separately.

The implementation uses a three-way handshake, a 14-byte header, an Internet
checksum, cumulative byte acknowledgments, a receive window, and timeout-based
retransmission. The receiver accepts in-order bytes and discards out-of-order
data; the maintained sender retransmits its outstanding window (Go-Back-N).

[Run locally](#run-locally) · [Validation](#validation) ·
[Original work and maintenance](#what-was-preserved-and-what-changed) · [Limits](#limitations)

Validation covers 27 tests and 17 localhost scenarios repeated three times
(51 runs), including lost packets, corruption, small windows, and close/accept
regressions. This is
an educational transport, not a production library or a claim of arbitrary-loss
reliability.

## Run locally

Only the Python standard library is needed. From this directory:

```sh
python3 -m unittest discover -s tests -v
python3 tests/scenario.py clean
python3 tests/scenario.py drop_data
python3 tests/scenario.py drop_fin_ack
```

The scenarios generate an 8,024-byte binary payload, use ephemeral UDP ports on
localhost, and compare every received byte. A deterministic proxy drops,
corrupts, duplicates, or injects a specific packet. Logs go into a temporary
directory. The small-final-chunk case uses five bytes; the empty case uses zero.
The test runner bounds each scenario to eight seconds so a broken protocol
cannot hang the whole suite. Standalone scenarios do not impose that deadline.

No datasets, network access to external hosts, course network simulator,
checkpoint downloads, or third-party libraries are needed.

## What was preserved and what changed

`historical/` contains byte-identical copies of the four original implementation
files and the three assignment write-ups. The original working directory was
not edited. Course-provided applications, simulator, and input text are not
included in this prepared copy.

The root implementation retains the original protocol structure. The follow-up
changes, made with Codex assistance in September 2026, are:

- Reject short/oversized datagrams before unpacking; constrain datagrams to the
  selected peer. This is filtering, not cryptographic authentication.
- Size the final chunk and narrow-window chunks correctly.
- Advertise remaining buffer space after accepting data, and probe a zero
  window when its reopening acknowledgment is lost.
- Retransmit the outstanding window after a timeout. Sending only its oldest
  segment caused very slow recovery because the receiver discarded the rest.
- Acknowledge repeated client FINs while the server remains running.
- Let a valid selected-peer FIN confirm a pending handshake when its final ACK
  was lost; empty streams can then close without needing a data packet.
- Remember completed handshakes so `accept()` still returns if the peer closed
  before the application started accepting. Buffered bytes remain readable,
  followed by EOF.
- Use a monotonic retransmission clock, close UDP sockets, return the sent byte
  count, and bind to localhost by default. Explicit `bind_addr` can override it.
- Reject non-integer byte-count configuration before allocating resources;
  close the allocated socket if binding, socket configuration, or log opening
  fails, without starting workers or masking the original error.
- Add independent checksum checks, bounded fault-injection scenarios, and
  configuration tests.

The new tests and packaging are follow-up maintenance work, not evidence that
these checks were present in the submitted assignment.

## Limitations

- One client, one-way application data. No congestion control, authentication,
  encryption, sequence-number wraparound, or network-path discovery.
- The APIs can wait indefinitely when a peer disappears or loss persists. The
  test subprocess deadline does not add a runtime connection deadline.
- If the final handshake ACK is lost and the client remains idle (sends neither
  data nor FIN), server `accept()` can still wait indefinitely. The server has
  no periodic SYN-ACK retransmission timer; the new FIN case is not a general
  idle-handshake recovery mechanism.
- Teardown tests exercise **client-initiated close with the server kept alive**
  until the client finishes. Server-initiated close, simultaneous close, delayed
  duplicate acknowledgments during teardown, and FIN recovery after server
  shutdown are not established by these tests.
- The receive queue is not bounded; this is not suitable for untrusted traffic.
- Selected deterministic faults do not establish arbitrary-loss reliability or
  WAN performance. No performance benchmark claim is made.
- The historical assignment's manual testing claims are preserved, not endorsed
  as independently reproduced. New checks use a separate deterministic proxy.

## Validation

All 27 tests passed on Python 3.12.3 and 3.14.0. Seventeen transport scenarios
passed three repeated runs (51 total) on Python 3.14.0 after the initialization
fixes. Five initialization test methods cover invalid types, valid integer
boundaries, acquisition failures, and preservation of the original exception
even if socket cleanup also raises an `OSError`. These tests inject failures
with mock resources and verify that workers are not started when acquisition
fails. The integer-boundary control passed before the fixes; the other four
test methods exposed failures against maintained commit `7b22598`.

This initialization-only change does not add connection deadlines or establish
recovery from worker startup failures. Sizes must be Python integers (not
booleans): 15–2,048 bytes for client segments, 1–65,535 for the server buffer.

The [earlier September 16 validation record](validation/validation-2026-09-16-py314.json)
preserves source hashes and scenario results from before the initialization
fixes; it does not describe the current source hashes.

The earlier handshake/accept regression cases are `drop_handshake_ack_empty` (drop exactly one
handshake ACK, send no DAT packets, then close and reach EOF) and
`closed_before_accept` (finish sending and closing before accepting, then read
the buffered five bytes and EOF). Both exceeded the bounded regression
deadline against the pre-fix maintained source before passing with these fixes.

The earlier [45-scenario record](validation/validation-py314.json) is preserved
unchanged. It includes bounded comparisons with the original assignment, not
the intermediate maintained source used for the two new regressions.

To run fresh comparisons locally:

```sh
python3 validate.py --repeats 3 --baseline --output results/validation.json
```

Some historical cases intentionally exceed the harness deadline. A timeout
does not prove a permanent deadlock; the packet-loss diagnostic showed slow
forward progress. Durations are observations, not portable performance claims.

## Attribution and publication

The original README identifies Junzhe Zong and the course. The project owner
confirmed publication clearance for this portfolio copy in September 2026.
This is not an instructor endorsement or permission to submit the code as
coursework. Course-provided applications, simulator, and data are excluded.
