#!/usr/bin/env python3
"""Answer key for asm/ram/mandel88.asm -- the Mandelbrot set in 8.8 fixed point.

mandel.asm draws in one-byte 1/32 units because there was no add-with-
carry. With ADC/SBB/ACI/SBI on silicon (2026-10-06) every value is a
signed 16-bit 8.8 number, 1/256 resolution, and the window is a set of RAM
cells you patch with W -- so the same program zooms.

Driven as the bench drives it: the REAL monitor image, the scripted serial
session, and what comes back on `tx` compared against a Python model of
the exact integer algorithm. Nothing here reads the .asm to decide what it
should print.

THE ARITHMETIC THE MODEL PINS. Squares only: 2xy = (x+y)^2 - x^2 - y^2.
sq(n) = floor(n*n / 256) for a magnitude n < 0x400, exactly, from a
256-byte table T[l] = floor(l*l / 256): with n = 256h + l,
    n*n / 256 = 256 h^2 + 2 h l + l*l/256
and the first two terms are integers, so the floor lands on T[l] alone.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import dinoload                                               # noqa: E402
import progrom_gen as pg                                      # noqa: E402
from microcode_gen import OPCODES, INSTRUCTIONS               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
MON = os.path.join(ROOT, "asm", "monitor.asm")
IMON = os.path.join(ROOT, "asm", "imon.asm")    # seated in U24, 2026-10-06
GAP = 250                       # imon: boundaries per typed character
SRC = os.path.join(ROOT, "asm", "ram", "mandel88.asm")
COLS, ROWS, MAXIT = 80, 33, 24
RAMP = b"  ..,,::;;--==++**xx%%##@"   # RAMP[it]; RAMP[MAXIT] is inside
RAMP_AT = 0x8103
WIN_AT = 0x811C                 # CX0, CY0, DX, DY: four 16-bit LE cells
DEFAULT = (-512, 256, 8, 16)    # -2.0, +1.0, 1/32, 1/16: mandel.asm's grid
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
def sq(n):
    assert 0 <= n < 0x400
    return n * n >> 8


def escape(cx, cy):
    """Iterations before escape, MAXIT if never. x, y signed 8.8."""
    x = y = 0
    for it in range(MAXIT):
        ax, ay = abs(x), abs(y)
        if ax >= 0x200 or ay >= 0x200:          # |x| or |y| >= 2
            return it
        x2, y2 = sq(ax), sq(ay)
        if x2 + y2 >= 0x400:                    # |z|^2 >= 4
            return it
        s2 = sq(abs(x + y))
        x, y = x2 - y2 + cx, s2 - x2 - y2 + cy
    return MAXIT


def ref_rows(win=DEFAULT):
    cx0, cy0, dx, dy = win
    out = []
    for r in range(ROWS):
        cy = cy0 - r * dy
        out.append(bytes(RAMP[escape(cx0 + c * dx, cy)] for c in range(COLS))
                   + b"\r\n")
    return b"".join(out)


def float_inside(win=DEFAULT):
    cx0, cy0, dx, dy = (v / 256 for v in win)
    cells = []
    for r in range(ROWS):
        for c in range(COLS):
            k = complex(cx0 + c * dx, cy0 - r * dy)
            z = 0j
            for _ in range(MAXIT):
                if abs(z) >= 2:
                    break
                z = z * z + k
            cells.append(abs(z) < 2)
    return cells


def win_cmd(win):
    """W lines that patch the window cells, one byte each."""
    out = b""
    for i, v in enumerate(win):
        v &= 0xFFFF
        out += b"W %04X,%02X\r" % (WIN_AT + 2 * i, v & 0xFF)
        out += b"W %04X,%02X\r" % (WIN_AT + 2 * i + 1, v >> 8)
    return out


# The edge of the main cardioid above elephant valley, x 0.28 .. 0.59,
# y 0.56 .. 0.31: 1/256 across and 1/128 down, 8x the default. The 1/32
# program has 10 columns across this whole window.
ZOOM = (72, 144, 1, 2)


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


def run(before_go=b"", src=MON, trace=None):
    image, _ = mon(src)
    r = program()
    script = (b"\r" + dinoload.load_line(r.origin, r.code)
              + dinoload.hexed(r.code) + before_go
              + dinoload.go_line(r.origin))
    kw = {"serial_gap": GAP} if src == IMON else {}
    if trace is not None:
        kw["trace"] = trace
    saved = pg.IDLE_QUIET_ENDS
    pg.IDLE_QUIET_ENDS = 400_000
    try:
        st = pg.simulate(None, image=image, serial_in=script,
                         max_steps=400_000_000, **kw)
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


# ---- tests --------------------------------------------------------------
def test_square_identity_is_exact():
    print("sq(256h + l) = 256h^2 + 2hl + T[l], exactly, for every n < 0x400")
    T = [l * l >> 8 for l in range(256)]
    bad = [n for n in range(0x400)
           if sq(n) != 256 * (n >> 8) ** 2 + 2 * (n >> 8) * (n & 0xFF)
           + T[n & 0xFF]]
    check_eq(bad, [], "no n disagrees")


def test_model_draws_the_mandelbrot_set():
    print("the 8.8 model agrees with floating point on inside/outside")
    for name, win in (("default", DEFAULT), ("zoom", ZOOM)):
        ref = ref_rows(win).split(b"\r\n")[:-1]
        got = [c == RAMP[MAXIT] for row in ref for c in row]
        want = float_inside(win)
        bad = sum(g != w for g, w in zip(got, want))
        # 2%, mandel.asm's allowance. At ZOOM the grid step IS the
        # arithmetic's resolution (1/256), so boundary cells truncate more
        # often: 45 of 2640 there, 14 at the default window.
        check(bad <= len(want) // 50,
              f"{name}: {bad} of {len(want)} cells disagree (<= 2%)")
        check(0 < sum(want) < len(want),
              f"{name}: inside and outside both present ({sum(want)} in)")


def test_layout_is_patchable():
    print("ramp at 0x8103, window cells at 0x811C, as the header promises")
    r = program()
    check_eq(r.labels.get("ramp"), RAMP_AT, "ramp label")
    check_eq(r.labels.get("win"), WIN_AT, "window label")
    check_eq(bytes(r.code[3:3 + MAXIT + 1]), RAMP, "ramp as loaded")
    w = bytes(r.code[WIN_AT - r.origin:WIN_AT - r.origin + 8])
    want = b"".join((v & 0xFFFF).to_bytes(2, "little") for v in DEFAULT)
    check_eq(w, want, "default window as loaded")


def test_calls_the_monitor_where_the_monitor_is():
    print("the .equ ROM addresses match the monitor's labels")
    _, labels = mon()
    r = program()
    for name in ("PUTC", "CRLF"):
        check_eq(r.labels.get(name), labels[name.lower()],
                 f"{name} = monitor's {name.lower()}")


def test_uses_the_carry_instructions():
    print("16-bit arithmetic is ADC/SBB, not a branch on the carry")
    r = program()
    code = bytes(r.code)
    for op in ("ADC", "SBB"):
        check(OPCODES[op] in code, f"{op} is in the program")


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


def test_zooms_when_the_window_is_patched():
    print("W into the window cells before G: 8x zoom, 1/256 across")
    out, _ = run(before_go=win_cmd(ZOOM))
    check_eq(out, ref_rows(ZOOM) + b"> ", "the zoomed picture, then prompt")


def test_ram_stays_clear_of_both_monitors():
    print("every RAM cell the program names is outside 0x80A0-0x80FF")
    r = program()
    cells = [v for k, v in r.labels.items() if k.isupper() and v >= 0x8000]
    cells += [0x8600, 0x86FF]                       # the square table
    bad = [hex(v) for v in cells if 0x80A0 <= v <= 0x80FF]
    check_eq(bad, [], "no cell in imon's ring/stack or the monitor's page")
    end = r.origin + len(r.code)
    check(end <= 0x8600, f"program ends at {end:#06x}, below the table")


def test_how_long_it_takes():
    """Not a pass/fail on speed: the number goes in the header and the
    log. T-states = sum of (1 + rows) per instruction, the machine's own
    cost rule; at 1.024 MHz one T-state is one clock."""
    print("T-states for the default picture, from the oracle's trace")
    cost = {OPCODES[n]: 1 + len(rows) for n, (_, rows) in INSTRUCTIONS.items()}
    name_cost = {n: 1 + len(rows) for n, (_, rows) in INSTRUCTIONS.items()}
    tr = []
    run(trace=tr)
    r = program()
    lo, hi = r.origin, 0x8600
    t = sum(name_cost[e["op"]] for e in tr
            if e["pc"] is not None and lo <= e["pc"] < hi)
    secs = t / 1.024e6
    print(f"       {t:,} T-states in the program ~ {secs:.1f} s at 1.024 MHz"
          f" (plus PUTC's wait on the wire)")
    check(t > 0 and cost, "measured")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nmandel88: OK")
