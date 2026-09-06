#!/usr/bin/env python3
"""Host tests for asm/monitor.asm -- the serial monitor.

The monitor is driven through simulate(serial_in=...), the scripted serial
stimulus (a test double, not a UART model -- see TestSerialScript in
test_progrom_gen.py). What is under test here is PARSING and FORMATTING:
hex in, hex out, the three commands, and every way a line can be wrong.
The polling loops are the bench-proven PROG_serrx idiom and are not what
these tests are for.

THE ANSWER KEY IS THE TRANSCRIPT. Every test compares the whole byte stream
the host would see, not a substring, so an extra CR or a missing prompt
fails by itself.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "asm", "monitor.asm")

BANNER = b"DINO MON\r\n"
PROMPT = b"> "
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
        r = asm.assemble_text(open(SRC).read())
        _IMAGE = pg.build_image_from_bytes(r.code, r.origin)
    return _IMAGE


def run(typed, **kw):
    """Type `typed` at the monitor; return (what the host saw, final state)."""
    st = pg.simulate(None, image=image(), serial_in=typed,
                     max_steps=2_000_000, **kw)
    return st["tx"], st


def transcript(*lines):
    """The exact byte stream for a list of (typed line, reply) pairs. A
    reply of None is a command that prints nothing (O, or an empty line)."""
    out = BANNER + PROMPT
    for typed, reply in lines:
        out += typed + b"\r\n"
        if reply is not None:
            out += reply + b"\r\n"
        out += PROMPT
    return out


def test_banner_and_prompt_then_idle():
    print("power-up")
    tx, st = run(b"")
    check_eq(tx, BANNER + PROMPT, "banner, prompt, then wait for a key")
    check(st["idle"] and not st["halted"], "never halts; idles on DR")


def test_the_session_from_the_ask():
    print("D / W / D / O, the session as specified (RAM is 0x8000+)")
    tx, st = run(b"D 8044\rW 8044,A5\rD 8044\rO 8044\r")
    check_eq(tx, transcript((b"D 8044", b"0x00"),
                            (b"W 8044,A5", b"0xA5"),
                            (b"D 8044", b"0xA5"),
                            (b"O 8044", None)),
             "the transcript, byte for byte")
    check_eq(st["out"], 0xA5, "O put the byte on OB")


def test_hex_is_forgiving_about_case_prefix_and_spaces():
    print("hex syntax")
    tx, _ = run(b"w 0x8044,0xa5\rd 0X8044\r  D   8044  \r")
    check_eq(tx, transcript((b"w 0x8044,0xa5", b"0xA5"),
                            (b"d 0X8044", b"0xA5"),
                            (b"  D   8044  ", b"0xA5")),
             "lowercase, 0x prefix, stray spaces all accepted")


def test_dump_reads_rom_and_write_to_rom_reads_back_the_rom_byte():
    print("addresses are the whole map, not a RAM offset")
    img = image()
    tx, _ = run(b"D 0\rD 0044\rW 44,A5\r")
    check_eq(tx, transcript((b"D 0", b"0x%02X" % img[0]),
                            (b"D 0044", b"0x%02X" % img[0x44]),
                            (b"W 44,A5", b"0x%02X" % img[0x44])),
             "D 0 is the reset vector; W into ROM reads back the ROM byte")


def test_every_hex_digit_and_the_high_nibble():
    print("formatting: all sixteen digits, both nibbles")
    lines, want = b"", []
    for i, v in enumerate((0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD,
                           0xEF, 0xF0, 0x0F, 0xFF, 0x10)):
        a = 0x8100 + i
        lines += b"W %04X,%02X\r" % (a, v)
        want.append((b"W %04X,%02X" % (a, v), b"0x%02X" % v))
    tx, _ = run(lines)
    check_eq(tx, transcript(*want), "every value round-trips in hex")


def test_bad_lines_get_a_question_mark_and_nothing_happens():
    print("errors")
    tx, st = run(b"X 8044\rD\rW 8044\rD 80G4\rW 8044,\rD 8044,1\r"
                 b"W 8045,5G\rD 8045\r")
    check_eq(tx, transcript((b"X 8044", b"?"),       # unknown command
                            (b"D", b"?"),            # no address
                            (b"W 8044", b"?"),       # no value
                            (b"D 80G4", b"?"),       # not hex
                            (b"W 8044,", b"?"),      # empty value
                            (b"D 8044,1", b"?"),     # D takes no value
                            (b"W 8045,5G", b"?"),    # bad value digit
                            (b"D 8045", b"0x00")),   # and it did not write
             "each malformed line is refused and leaves memory alone")
    check(st["out"] in (None, 0xFF), "nothing reached OB but the poison")


def test_empty_line_and_lf_are_harmless():
    print("line discipline")
    tx, _ = run(b"\r\n\rD 8044\r\n")
    check_eq(tx, transcript((b"", None), (b"", None), (b"D 8044", b"0x00")),
             "CR alone reprompts; LF is swallowed")


def test_long_hex_keeps_the_last_four_digits():
    print("a 16-bit address is four digits; extra leading digits fall off")
    tx, _ = run(b"W 8046,B7\rD 18046\rW 8046,1C3\rD 8046\r")
    check_eq(tx, transcript((b"W 8046,B7", b"0xB7"),
                            (b"D 18046", b"0xB7"),
                            (b"W 8046,1C3", b"0xC3"),
                            (b"D 8046", b"0xC3")),
             "the shift register keeps the low four nibbles")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nmonitor: OK")
