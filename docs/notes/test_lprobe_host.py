#!/usr/bin/env python3
"""Host tests for docs/notes/lprobe_host.py -- the raw L-path probe.

Same OraclePort as test_dinoload: the far end is the REAL monitor image
through simulate(serial_in=...). The probe must (1) report zero wrong and
a matching sum against a perfect monitor, and (2) name the position and
the byte when one echo comes back wrong, and stop there.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lprobe_host                                            # noqa: E402
from test_dinoload import OraclePort                          # noqa: E402

FAILS = []


def check(cond, label):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        FAILS.append(label)


class LyingPort:
    """OraclePort, except the Nth byte the HOST writes reaches the monitor
    as `lie`. Models the bench: the CPU reads 0x00 off RBR where a digit
    was typed, echoes it, and hexval aborts the load with `?`."""

    def __init__(self, nth, lie=b"\x00"):
        self.inner = OraclePort()
        self.nth, self.lie, self.seen = nth, lie, 0

    def write(self, data):
        for b in bytes(data):
            self.inner.write(self.lie if self.seen == self.nth else bytes([b]))
            self.seen += 1

    def read_until(self, delim, timeout=1.0):
        return self.inner.read_until(delim, timeout)


CODE = bytes([0x11, 0x5A, 0x51, 0x34])          # LDAI 0x5A; OUT; RET


def test_clean_monitor_is_zero_wrong():
    print("clean")
    lines = []
    r = lprobe_host.probe(OraclePort(), CODE, 0x8100, gap=0.0, out=lines.append)
    check(r["wrong_line"] == 0, "L line echoes all match")
    check(r["wrong_payload"] == 0, "payload echoes all match")
    check(r["abort_at"] is None, "no abort")
    check(r["sum_got"] == r["sum_want"] == sum(CODE) & 0xFF,
          f"sum {r['sum_got']!r} == {r['sum_want']:#04x}")
    check(any("wrong" in ln for ln in lines), "a summary line was printed")


def test_one_lying_echo_is_named_and_stops():
    print("lying")
    # host bytes before the first payload digit: the sync CR, then the line
    pre = 1 + len(lprobe_host.l_line(0x8100, len(CODE)))
    lines = []
    r = lprobe_host.probe(LyingPort(pre), CODE, 0x8100, gap=0.0,
                          out=lines.append)
    check(r["wrong_line"] == 0, "L line clean")
    check(r["wrong_payload"] >= 1, "payload has a wrong echo")
    check(r["positions"] and r["positions"][0] == 0,
          f"first wrong position is 0, got {r['positions']}")
    check(r["wrong_bytes"].get(0x00, 0) >= 1, "the wrong byte was 0x00")
    check(r["abort_at"] is not None, "monitor aborted with ? and probe stopped")
    check(r["sum_got"] is None, "no sum after an abort")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED"); return 1
    print("\nOK"); return 0


if __name__ == "__main__":
    sys.exit(main())
