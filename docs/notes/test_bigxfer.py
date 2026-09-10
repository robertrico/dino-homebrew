#!/usr/bin/env python3
"""Answer key for asm/ram/bigxfer.asm -- the serial settle test.

Driven exactly as the bench drives it: the REAL monitor image, a scripted
serial session -- sync, `L 8100,len`, the hex, `G 8100`. The program then
streams ITSELF back, every byte from its origin to its end, as hex, and
ends with a line carrying a 16-bit sum and an 8-bit xor. Both are computed
here independently from the assembled bytes; nothing reads the .asm to
decide what it should print. The parser under test is the one
bigxfer_host.py uses on the bench.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import dinoload                                               # noqa: E402
import progrom_gen as pg                                      # noqa: E402
import bigxfer_host                                           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
MON = os.path.join(ROOT, "asm", "monitor.asm")
SRC = os.path.join(ROOT, "asm", "ram", "bigxfer.asm")
FAILS = []


def check(cond, label):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILS.append(label)


_MON = None


def mon():
    global _MON
    if _MON is None:
        r = asm.assemble_text(open(MON).read())
        _MON = (pg.build_image_from_bytes(r.code, r.origin), r.labels)
    return _MON


def program():
    r = asm.assemble_text(open(SRC).read())
    dinoload.check_placement(r.code, r.origin)
    return r


def session():
    image, _ = mon()
    r = program()
    script = (b"\r" + dinoload.load_line(r.origin, r.code)
              + dinoload.hexed(r.code) + dinoload.go_line(r.origin))
    st = pg.simulate(None, image=image, serial_in=script,
                     max_steps=60_000_000)
    tx = st["tx"]
    go_echo = b"G %04X\r\n" % r.origin
    i = tx.rfind(go_echo)
    check(i >= 0, "the monitor echoed the G line")
    return r, tx[i + len(go_echo):], st


def test_calls_the_monitor_where_the_monitor_is():
    print("ROM addresses")
    _, labels = mon()
    r = program()
    for name in ("PUTHEX", "CRLF", "PUTC"):
        check(r.labels.get(name) == labels[name.lower()],
              f"{name} = {labels[name.lower()]:#06x}")


def test_is_large():
    print("size")
    r = program()
    check(len(r.code) >= 2048, f"{len(r.code)} bytes, at least 2K")
    check(r.origin == 0x8100, "origin 0x8100")


def test_streams_itself_back_exactly():
    print("stream")
    r, out, st = session()
    rep = bigxfer_host.parse(out, r.code)
    check(rep["ok"], "parse ok")
    check(rep["n"] == len(r.code), f"{rep['n']} bytes streamed of {len(r.code)}")
    check(rep["first_diff"] is None, f"first diff {rep['first_diff']}")
    want16 = sum(r.code) & 0xFFFF
    wantx = 0
    for b in r.code:
        wantx ^= b
    check(rep["sum16"] == want16, f"sum16 {rep['sum16']:#06x} == {want16:#06x}")
    check(rep["xor"] == wantx, f"xor {rep['xor']:#04x} == {wantx:#04x}")
    check(out.endswith(dinoload.PROMPT), "RET landed on the prompt")
    check(not st.get("halted"), "did not HALT")


def test_parser_names_a_bad_byte():
    print("parser")
    code = bytes(range(64))
    good = bigxfer_host.render(code)
    rep = bigxfer_host.parse(good, code)
    check(rep["ok"] and rep["first_diff"] is None, "clean transcript parses clean")
    bad = good.replace(b"1F", b"1E", 1)              # byte 31 wrong
    rep = bigxfer_host.parse(bad, code)
    check(rep["first_diff"] == 31, f"first diff is 31, got {rep['first_diff']}")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED"); return 1
    print("\nOK"); return 0


if __name__ == "__main__":
    sys.exit(main())
