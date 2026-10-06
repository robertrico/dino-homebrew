#!/usr/bin/env python3
"""Answer key for asm/ram/mandel.asm -- the Mandelbrot set on the terminal.

Driven as the bench drives it: the REAL monitor image, the scripted serial
session (sync, `L 8100,len`, hex, `G 8100`), and what comes back on `tx`
after the G line compared against a Python model written from the
arithmetic the header documents. Nothing here reads the .asm to decide
what it should print.

Two references, because the first is only as good as its own idea of the
arithmetic:
  ref_rows()    the exact integer algorithm: 1/32 units, offset binary,
                floor-of-square tables. Byte for byte.
  float_rows()  the textbook escape-time Mandelbrot in floating point on
                the same grid. Must agree on inside/outside for nearly
                every cell, or the integer scheme draws the wrong picture
                exactly.
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
IMON = os.path.join(ROOT, "asm", "imon.asm")    # seated in U24, 2026-10-06
GAP = 250                       # imon: boundaries per typed character
SRC = os.path.join(ROOT, "asm", "ram", "mandel.asm")
COLS = 80                       # cx = (col - 64)/32: -2.0 .. +0.47
ROWS = 33                       # cy = (32 - 2*row)/32: +1.0 .. -1.0
MAXIT = 24
RAMP = b"  ..,,::;;--==++**xx%%##@"   # RAMP[it]; RAMP[MAXIT] is inside
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


# ---- the integer model --------------------------------------------------
S = [n * n // 32 for n in range(64)]        # x^2 in 1/32 units, |x| < 2
Q = [n * n // 64 for n in range(127)]       # (a^2)/64: 2xy = Q[a+b]-Q[|a-b|]


def escape(cxo, cyo):
    """Iterations before escape, MAXIT if never. All values offset by 64
    (0.0 = 64) so every range check is an unsigned compare and a carry."""
    xo = yo = 64
    for it in range(MAXIT):
        ax, sx = (xo - 64, 0) if xo >= 64 else (64 - xo, 1)
        ay, sy = (yo - 64, 0) if yo >= 64 else (64 - yo, 1)
        if S[ax] + S[ay] >= 128:            # |z|^2 >= 4
            return it
        u = S[ax] + cxo - S[ay]             # x' + 64
        if u < 0 or u >= 128 or u == 0:     # |x'| >= 2
            return it
        m = Q[ax + ay] - Q[abs(ax - ay)]    # |2xy|
        v = cyo - m if sx != sy else cyo + m
        if v <= 0 or v >= 128:              # |y'| >= 2
            return it
        xo, yo = u, v
    return MAXIT


def ref_rows():
    out = []
    for r in range(ROWS):
        cyo = 96 - 2 * r
        out.append(bytes(RAMP[escape(col, cyo)] for col in range(COLS))
                   + b"\r\n")
    return b"".join(out)


def float_inside():
    cells = []
    for r in range(ROWS):
        cy = (32 - 2 * r) / 32
        for col in range(COLS):
            c = complex((col - 64) / 32, cy)
            z = 0j
            for _ in range(MAXIT):
                if abs(z) >= 2:
                    break
                z = z * z + c
            cells.append(abs(z) < 2)
    return cells


# ---- the session --------------------------------------------------------
_MON = {}


def mon(src=MON):
    if src not in _MON:
        r = asm.assemble_text(open(src).read())
        _MON[src] = (pg.build_image_from_bytes(r.code, r.origin), r.labels)
    return _MON[src]


def program():
    r = asm.assemble_text(open(SRC).read())
    dinoload.check_placement(r.code, r.origin)
    return r


def run(before_go=b"", src=MON):
    image, _ = mon(src)
    r = program()
    script = (b"\r" + dinoload.load_line(r.origin, r.code)
              + dinoload.hexed(r.code) + before_go
              + dinoload.go_line(r.origin))
    kw = {"serial_gap": GAP} if src == IMON else {}
    # imon's idle rule (RDA on, script spent, IDLE_QUIET_ENDS boundaries
    # with no UART access) reads the table build and any 24-iteration cell
    # as "waiting at the prompt". The longest quiet stretch is the build,
    # well under 200k; the prompt after RET still goes idle.
    saved = pg.IDLE_QUIET_ENDS
    pg.IDLE_QUIET_ENDS = 200_000
    try:
        st = pg.simulate(None, image=image, serial_in=script,
                         max_steps=200_000_000, **kw)
    finally:
        pg.IDLE_QUIET_ENDS = saved
    tx = st["tx"]
    go_echo = b"G %04X\r\n" % r.origin
    i = tx.rfind(go_echo)
    check(i >= 0, "the monitor echoed the G line")
    return tx[i + len(go_echo):], st


_RUN = {}


def picture(src=MON):
    if src not in _RUN:
        _RUN[src] = run(src=src)
    return _RUN[src]


def test_model_draws_the_mandelbrot_set():
    print("the integer model agrees with floating point on inside/outside")
    ref = ref_rows().split(b"\r\n")[:-1]
    got = [c == RAMP[MAXIT] for row in ref for c in row]
    want = float_inside()
    bad = sum(g != w for g, w in zip(got, want))
    check(bad <= len(want) // 50,
          f"{bad} of {len(want)} cells disagree (<= 2% allowed)")
    check(sum(want) > 300, f"the set is there: {sum(want)} cells inside")


def test_calls_the_monitor_where_the_monitor_is():
    print("the .equ ROM addresses match the monitor's labels")
    _, labels = mon()
    r = program()
    for name in ("PUTC", "CRLF"):
        check_eq(r.labels.get(name), labels[name.lower()],
                 f"{name} = monitor's {name.lower()}")
    check_eq(r.labels.get("ramp"), 0x8103,
             "the ramp is at 0x8103, as the header promises")
    check_eq(bytes(r.code[3:3 + MAXIT + 1]), RAMP, "ramp as loaded")


def _draws(src, name):
    print(f"{name}: G 8100, 33 rows of 80, byte for byte, then the prompt")
    out, st = picture(src)
    want = ref_rows()
    for k, (g, w) in enumerate(zip(out.split(b"\r\n"),
                                   want.split(b"\r\n")[:-1])):
        if g != w:
            check_eq(g, w, f"row {k}")
            break
    check_eq(out, want + b"> ", "the whole picture, then the prompt")
    check_eq(st["idle"], True, "back at the monitor's prompt")
    check_eq(st["out"], ROWS, "OB counts the rows printed")
    check(not st["hit_poison"], "PC never escaped to the poison")


def test_draws_the_picture_under_monitor():
    _draws(MON, "PROG_monitor")


def test_draws_the_picture_under_imon():
    _draws(IMON, "PROG_imon")


def test_ram_stays_clear_of_both_monitors():
    print("every RAM cell the program names is outside 0x80A0-0x80FF")
    r = program()
    cells = [v for k, v in r.labels.items() if k.isupper() and v >= 0x8000]
    cells += [0x8600, 0x8680 + 126]                  # the two tables' ends
    bad = [hex(v) for v in cells if 0x80A0 <= v <= 0x80FF]
    check_eq(bad, [], "no cell in imon's ring/stack or the monitor's page")
    end = r.origin + len(r.code)
    check(end <= 0x8600, f"program ends at {end:#06x}, below the tables")


def test_ramp_is_patchable_from_the_monitor():
    print("W into the ramp before G: the inside character changes")
    out, _ = run(before_go=b"W 811B,23\r")          # ramp[24] = '#'
    want = ref_rows().replace(b"@", b"#")
    check_eq(out, want + b"> ", "inside drawn as '#'")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nmandel: OK")
