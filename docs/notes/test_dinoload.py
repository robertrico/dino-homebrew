#!/usr/bin/env python3
"""Host tests for docs/notes/dinoload.py -- the L/G loader.

The port under the loader is OraclePort: a fake serial port whose far end
is the REAL monitor image run through simulate(serial_in=...). Every write
appends to the script, every read re-runs the whole session and hands back
the transcript's unread tail. Deterministic, so replaying is exact. What is
under test is the PROTOCOL: the sync, the L line, the raw stream, the sum
check, the G line -- against the same bytes the chip will see.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import dinoload                                               # noqa: E402
import progrom_gen as pg                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
MON = os.path.join(ROOT, "asm", "monitor.asm")
FAILS = []


def check(cond, label):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILS.append(label)


def check_eq(got, want, label):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")
        FAILS.append(label)


_IMAGE = None


def image():
    global _IMAGE
    if _IMAGE is None:
        r = asm.assemble_text(open(MON).read())
        _IMAGE = pg.build_image_from_bytes(r.code, r.origin)
    return _IMAGE


class OraclePort:
    """The monitor, as a serial port."""

    def __init__(self):
        self.script = bytearray()
        self.consumed = 0
        self.last = None

    def write(self, data):
        self.script += bytes(data)

    def _run(self):
        self.last = pg.simulate(None, image=image(), serial_in=bytes(self.script),
                                max_steps=5_000_000)
        return self.last["tx"]

    def read_until(self, delim, timeout=1.0):
        tx = self._run()
        tail = tx[self.consumed:]
        i = tail.find(delim)
        if i < 0:
            self.consumed = len(tx)
            return tail
        self.consumed += i + len(delim)
        return tail[:i + len(delim)]

    def close(self):
        pass


def prog(text, org=0x8100):
    return asm.assemble_text(f"          .org {org:#06x}\n" + text)


def test_frames_are_the_monitor_language():
    print("framing")
    r = prog("LDAI 0x5A\nOUT\nRET\n")
    check_eq(dinoload.load_line(r.origin, r.code), b"L 8100,4\r",
             "L addr,len in the monitor's hex: LDAI is two bytes")
    check_eq(dinoload.go_line(0x8100), b"G 8100\r", "G addr")
    op = asm.OPCODES
    check_eq(dinoload.csum(r.code),
             (op["LDAI"] + 0x5A + op["OUT"] + op["RET"]) & 0xFF,
             "8-bit sum of the payload")
    check_eq(dinoload.hexed(r.code),
             b"%02X5A%02X%02X" % (op["LDAI"], op["OUT"], op["RET"]),
             "the payload is upper-case hex text, typeable at minicom")


def test_a_wrong_echo_is_a_named_error():
    print("a chunk echoed wrong stops the load before the sum")
    r = prog("LDAI 0x5A\nOUT\nRET\n")

    class Garbler(OraclePort):
        def read_until(self, delim, timeout=1.0):
            got = super().read_until(delim, timeout)
            if delim == dinoload.hexed(r.code):       # the payload chunk
                got = got.replace(b"5A", b"5B")
            return got
    port = Garbler()
    try:
        dinoload.load(port, r.code, r.origin)
    except dinoload.LoadError as e:
        check("echo" in str(e), f"LoadError names the echo: {e}")
    else:
        check(False, "no LoadError on a garbled echo")


def test_load_streams_the_bytes_and_checks_the_sum():
    print("load: sync, L, stream, sum")
    r = prog("LDAI 0x5A\nOUT\nRET\n")
    port = OraclePort()
    got = dinoload.load(port, r.code, r.origin)
    check_eq(got, dinoload.csum(r.code), "the monitor answered the sum")
    check_eq(port.last["idle"], True, "monitor back on the prompt")
    # the bytes are really there: ask the monitor
    port.write(b"D 8100\r")
    check_eq(port.read_until(b"> "), b"D 8100\r\n0x11\r\n> ",
             "D reads back the first byte")


def test_a_wrong_sum_is_a_named_error():
    print("a bad sum raises, and says both sums")
    r = prog("LDAI 0x5A\nOUT\nRET\n")

    class SumLiar(OraclePort):
        # the echo was perfect; what LANDED was not (a STAX that missed)
        def read_until(self, delim, timeout=1.0):
            got = super().read_until(delim, timeout)
            if delim == dinoload.PROMPT and b"0x" in got:
                got = got.replace(b"0xF0", b"0xF1")
            return got
    port = SumLiar()
    try:
        dinoload.load(port, r.code, r.origin)
    except dinoload.LoadError as e:
        check("sum mismatch" in str(e), f"LoadError names the sum: {e}")
    else:
        check(False, "no LoadError on a wrong sum")


def test_sync_swallows_a_stray_byte_and_flushes_first():
    print("a stray 0x81 in the FTDI buffer before the prompt is not fatal")
    r = prog("LDAI 0x5A\nOUT\nRET\n")

    class Stray(OraclePort):
        flushed = 0
        junk = b"\x81"

        def flush_input(self):
            self.flushed += 1

        def read_until(self, delim, timeout=1.0):
            got = super().read_until(delim, timeout)
            j, self.junk = self.junk, b""
            return j + got
    port = Stray()
    got = dinoload.load(port, r.code, r.origin)
    check_eq(got, dinoload.csum(r.code), "loaded through the junk")
    check_eq(port.flushed, 1, "the input queue was flushed before sync")


def test_go_runs_it_and_returns_the_output():
    print("go: G addr, then whatever the program prints up to the prompt")
    labels = asm.assemble_text(open(MON).read()).labels
    r = prog(f"LDAI 'H'\nCALL {labels['putc']:#06x}\n"
             f"LDAI 'I'\nCALL {labels['putc']:#06x}\n"
             f"CALL {labels['crlf']:#06x}\nRET\n")
    port = OraclePort()
    dinoload.load(port, r.code, r.origin)
    out = dinoload.go(port, r.origin)
    check_eq(out, b"HI\r\n", "the program's own output, prompt stripped")
    check_eq(port.last["idle"], True, "RET returned to the prompt")


def test_go_to_a_halting_program_reports_no_prompt():
    print("go: a HALT never comes back")
    r = prog("LDAI 0x3C\nOUT\nHALT\n")
    port = OraclePort()
    dinoload.load(port, r.code, r.origin)
    out = dinoload.go(port, r.origin)
    check_eq(out, None, "None: no prompt came back")
    check_eq(port.last["halted"], True, "the oracle halted")
    check_eq(port.last["out"], 0x3C, "and OB has the answer")


def test_refuses_rom_and_monitor_state():
    print("addresses the loader will not load")
    for org, why in ((0x0100, "ROM"), (0x80F0, "the monitor's own cells")):
        r = prog("RET\n", org)
        try:
            dinoload.check_placement(r.code, r.origin)
        except dinoload.LoadError:
            check(True, f"refused {org:#06x} ({why})")
        else:
            check(False, f"accepted {org:#06x} ({why})")
    r = prog("RET\n", 0x8100)
    dinoload.check_placement(r.code, r.origin)
    check(True, "0x8100 accepted")


def test_assemble_file_gives_code_and_origin():
    print("the .asm path")
    src = os.path.join(ROOT, "asm", "ram", "hello.asm")
    code, origin = dinoload.assemble_file(src)
    check_eq(origin, 0x8100, "asm/ram/hello.asm sits at 0x8100")
    check(len(code) > 0 and code[-1] == asm.OPCODES["RET"],
          "and ends with RET, so G comes back")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\ndinoload: OK")
