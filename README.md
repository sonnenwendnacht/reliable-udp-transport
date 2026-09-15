# Reliable UDP transport study

**Local preparation only — not cleared for public upload.** This folder is a
tested follow-up to Junzhe Zong's CSEE 4119 Spring 2026 assignment 2. It is not a
new independently authored project or a production transport library.

The implementation uses a three-way handshake, a 14-byte header, an Internet
checksum, cumulative byte acknowledgments, a receive window, and timeout-based
retransmission. The receiver accepts in-order bytes and discards out-of-order
data; the prepared sender retransmits its outstanding window (Go-Back-N).

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
- Use a monotonic retransmission clock, close UDP sockets, return the sent byte
  count, and bind to localhost by default. Explicit `bind_addr` can override it.
- Add independent checksum checks, bounded fault-injection scenarios, and
  configuration tests.

The new tests and packaging are follow-up maintenance work, not evidence that
these checks were present in the submitted assignment.

## Limitations

- One client, one-way application data. No congestion control, authentication,
  encryption, sequence-number wraparound, or network-path discovery.
- The APIs can wait indefinitely when a peer disappears or loss persists. The
  test subprocess deadline does not add a runtime connection deadline.
- Teardown tests exercise **client-initiated close with the server kept alive**
  until the client finishes. Server-initiated close, simultaneous close, delayed
  duplicate acknowledgments during teardown, and FIN recovery after server
  shutdown are not established by these tests.
- The receive queue is not bounded; this is not suitable for untrusted traffic.
- Selected deterministic faults do not establish arbitrary-loss reliability or
  WAN performance. No performance benchmark claim is made.
- The historical assignment's manual testing claims are preserved, not endorsed
  as independently reproduced. New checks use a separate deterministic proxy.

## Publication status and attribution

The original README identifies Junzhe Zong and the course. Sharing terms for the
Spring 2026 assignment have not been established. An older offering explicitly
prohibited public solutions; that is a warning, not proof of the current terms:
[CSEE 4119 Fall 2020 syllabus](https://www.columbia.edu/~ebk2141/teaching/csee4119/2020FA/2020Fall-4119-info_and_syllabus.pdf).

Do not push this folder, choose a public license, or copy course material into
it until the applicable sharing permission is confirmed. This local Git
repository deliberately has no remote configured.
