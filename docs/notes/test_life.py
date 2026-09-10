#!/usr/bin/env python3
"""Answer key for asm/ram/life.asm -- the RAM-resident Rule 30 automaton.

The program is driven exactly as the bench drives it: through the REAL
monitor image, over the scripted serial session -- sync, `L 8100,len`, the
hex, `G 8100`, then the keys a person would type. What comes back on `tx`
after the G line is the program's own output, and it is compared against
an independent Python automaton, cell for cell. Nothing here reads the
.asm to decide what it should print.

The oracle's UART double has no clock: DR is "bytes remain in the script",
so the program sees the typed key at its FIRST poll. `x\\r` therefore means
"one row, a key that is not Enter, a second row, Enter, back to the prompt".
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
SRC = os.path.join(ROOT, "asm", "ram", "life.asm")
WIDTH = 64
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


# ---- the reference automaton, written from the definition ---------------
def seed(sw):
    cells = [0] * WIDTH
    for bit in range(8):                    # bit 7 -> cell 29, bit 0 -> 36
        cells[28 + bit] = (sw >> (7 - bit)) & 1
    if sw == 0:
        cells[31] = 1                       # cell 32, the classic triangle
    return cells


def step(cells, rule):
    out = []
    for i in range(WIDTH):
        left = cells[i - 1] if i > 0 else 0
        right = cells[i + 1] if i < WIDTH - 1 else 0
        out.append((rule >> (left * 4 + cells[i] * 2 + right)) & 1)
    return out


def rows(sw, n, rule=30):
    cells = seed(sw)
    lines = []
    for _ in range(n):
        lines.append("".join("#" if c else " " for c in cells).encode()
                     + b"\r\n")
        cells = step(cells, rule)
    return b"".join(lines)


# ---- the session --------------------------------------------------------
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


def session(keys, sw=0, before_go=b""):
    """Load, optionally poke, run. Returns (program output, oracle state)."""
    image, _ = mon()
    r = program()
    script = (b"\r" + dinoload.load_line(r.origin, r.code)
              + dinoload.hexed(r.code) + before_go
              + dinoload.go_line(r.origin) + keys)
    st = pg.simulate(None, image=image, serial_in=script, switches=sw,
                     max_steps=20_000_000)
    tx = st["tx"]
    go_echo = b"G %04X\r\n" % r.origin
    i = tx.rfind(go_echo)
    check(i >= 0, "the monitor echoed the G line")
    out = tx[i + len(go_echo):]
    return out, st


def test_calls_the_monitor_where_the_monitor_is():
    print("the .equ ROM addresses match the monitor's labels")
    _, labels = mon()
    r = program()
    for name in ("PUTC", "CRLF"):
        check_eq(r.labels.get(name), labels[name.lower()],
                 f"{name} = monitor's {name.lower()}")
    check_eq(r.labels.get("rule"), 0x8103,
             "the rule table is at 0x8103, as the header promises")
    check_eq(r.code[-1], asm.OPCODES["RET"], "ends with RET")


def test_enter_stops_it_after_one_row():
    print("Enter alone: one row, then the prompt")
    out, st = session(b"\r")
    check_eq(out, rows(0, 1) + b"> ", "row 0 of the single-centre seed")
    check_eq(st["idle"], True, "back at the monitor's prompt")
    check_eq(st["out"], 1, "OB counts the rows printed")


def test_other_keys_are_eaten_and_it_keeps_going():
    print("a key that is not Enter: swallowed, the next row follows")
    out, st = session(b"x\r")
    check_eq(out, rows(0, 2) + b"> ", "rows 0 and 1, Rule 30")
    check_eq(st["out"], 2, "OB = 2")


def test_many_generations_match_the_reference():
    print("40 generations of Rule 30 from the centre cell")
    out, _ = session(b"x" * 39 + b"\r")
    check_eq(out, rows(0, 40) + b"> ", "cell for cell")


def test_sw1_seeds_the_row():
    print("SW1 is the seed: bits 7..0 land in cells 29..36")
    for sw in (0xA5, 0x01, 0x80, 0xFF):
        out, _ = session(b"x\r", sw=sw)
        check_eq(out, rows(sw, 2) + b"> ", f"SW1={sw:#04x}")


def test_free_run_scrolls_without_a_key():
    """THE BENCH'S ACTUAL MODE. With nobody typing, every generation takes
    the `JNZ key`-not-taken -> `JMP main` branch, and the default serial
    double STOPS at the first keyless LSR poll (idle after 3 empty reads) --
    so the ordinary tests, which feed one key per generation, never exercise
    it. Raise the idle threshold and feed no keys: the scroll must run many
    generations, match the reference, and never escape to the poison."""
    saved = pg.IDLE_LSR_READS
    pg.IDLE_LSR_READS = 10**9
    try:
        image, _ = mon()
        r = program()
        script = (b"\r" + dinoload.load_line(r.origin, r.code)
                  + dinoload.hexed(r.code) + dinoload.go_line(r.origin))
        st = pg.simulate(None, image=image, serial_in=script, switches=0,
                         max_steps=4_000_000)
    finally:
        pg.IDLE_LSR_READS = saved
    tx = st["tx"]
    body = tx[tx.rfind(b"G 8100\r\n") + len(b"G 8100\r\n"):]
    n = 30
    check_eq(body[:len(rows(0, n))], rows(0, n),
             f"the first {n} free-run rows match Rule 30, no key typed")
    check(not st["hit_poison"], "PC never escaped to the poison")


def test_rule_table_is_patchable_from_the_monitor():
    print("W into the table before G: Rule 110")
    poke = b"W 8107,0\rW 8108,1\rW 8109,1\r"
    out, _ = session(b"x" * 15 + b"\r", before_go=poke)
    check_eq(out, rows(0, 16, rule=110) + b"> ", "16 rows of Rule 110")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nlife: OK")
