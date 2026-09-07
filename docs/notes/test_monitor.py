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

# ---- L and G: load hex text, run it -----------------------------------------
def ram_prog(text, org=0x8100):
    """Assemble a RAM-resident program; return its bytes."""
    return asm.assemble_text(f"          .org {org:#06x}\n" + text).code


def load_line(org, data):
    return b"L %04X,%X" % (org, len(data))


def hexed(data):
    return data.hex().upper().encode()


def csum(data):
    return b"0x%02X" % (sum(data) & 0xFF)


def lpair(org, data, payload=None):
    """The (typed, reply) pair for an L: the line, its CRLF, the echoed
    payload, then the sum. `payload` overrides the hex text sent; CR and
    LF inside it are skipped and NOT echoed, like the line parser."""
    payload = hexed(data) if payload is None else payload
    echo = payload.replace(b"\r", b"").replace(b"\n", b"")
    return (load_line(org, data) + b"\r\n" + echo, csum(data))


def ltyped(org, data, payload=None):
    payload = hexed(data) if payload is None else payload
    return load_line(org, data) + b"\r" + payload


def test_load_takes_hex_text_and_answers_the_sum():
    print("L addr,len: hex digits land in RAM, the reply is their 8-bit sum")
    data = bytes([0x0D, 0x0A, 0x00, 0xFF, 0x3F, 0x4C, 0x44])
    typed = ltyped(0x8200, data) + b"D 8200\rD 8203\rD 8206\r"
    tx, st = run(typed)
    check_eq(tx, transcript(lpair(0x8200, data),
                            (b"D 8200", b"0x0D"),
                            (b"D 8203", b"0xFF"),
                            (b"D 8206", b"0x44")),
             "the payload is echoed, then CRLF, then the sum")
    check(st["idle"] and not st["halted"], "back at the prompt")


def test_hex_payload_is_forgiving():
    print("lower case, spaces, CR and LF inside the payload are fine")
    data = bytes([0xAB, 0xCD, 0x12])
    payload = b"ab cd\r\n 12"
    typed = ltyped(0x8100, data, payload) + b"D 8101\r"
    tx, _ = run(typed)
    check_eq(tx, transcript(lpair(0x8100, data, payload),
                            (b"D 8101", b"0xCD")),
             "whitespace is skipped and not counted; case folds")


def test_bad_hex_in_the_payload_aborts_with_a_question_mark():
    print("a non-hex character stops the load")
    data = bytes([0x11, 0x22, 0x33])
    typed = ltyped(0x8100, data, b"11G2\r") + b"D 8100\rD 8101\r"
    tx, _ = run(typed)
    check_eq(tx, BANNER + PROMPT
             + b"L 8100,3\r\n11G\r\n?\r\n" + PROMPT
             + b"2\r\n?\r\n" + PROMPT              # the 2 became a line
             + b"D 8100\r\n0x11\r\n" + PROMPT
             + b"D 8101\r\n0x00\r\n" + PROMPT,
             "`?`; the bytes already landed stay, the rest never arrive")


def test_load_length_is_sixteen_bit():
    print("a length above 0xFF walks the pointer's high byte")
    data = bytes((i * 7) & 0xFF for i in range(0x110))
    typed = ltyped(0x8100, data) + b"D 81FF\rD 8200\rD 820F\r"
    tx, _ = run(typed)
    check_eq(tx, transcript(lpair(0x8100, data),
                            (b"D 81FF", b"0x%02X" % data[0xFF]),
                            (b"D 8200", b"0x%02X" % data[0x100]),
                            (b"D 820F", b"0x%02X" % data[0x10F])),
             "bytes 0x100+ land at 0x8200+, and the sum wraps")


def test_load_needs_a_length():
    print("L without a length is refused")
    tx, _ = run(b"L 8100\rL 8100,\r")
    check_eq(tx, transcript((b"L 8100", b"?"), (b"L 8100,", b"?")),
             "no length, empty length: `?` and nothing is read")


def test_go_runs_the_loaded_program_and_ret_comes_back():
    print("G addr: CALL into RAM; RET returns to the prompt")
    prog = ram_prog("""
          LDAI  0x5A
          OUT
          RET
    """)
    typed = ltyped(0x8100, prog) + b"G 8100\rD 8100\r"
    tx, st = run(typed)
    check_eq(tx, transcript(lpair(0x8100, prog),
                            (b"G 8100", None),
                            (b"D 8100", b"0x%02X" % prog[0])),
             "G prints nothing; RET lands on the next prompt")
    check_eq(st["out"], 0x5A, "the loaded program ran and reached OB")
    check(st["idle"] and not st["halted"], "monitor is back on DR")


def test_go_program_may_use_the_monitor_subroutines():
    print("a loaded program can CALL putc/crlf by ROM address")
    labels = asm.assemble_text(open(SRC).read()).labels
    prog = ram_prog(f"""
          LDAI  'H'
          CALL  {labels['putc']:#06x}
          LDAI  'I'
          CALL  {labels['putc']:#06x}
          CALL  {labels['crlf']:#06x}
          RET
    """)
    typed = ltyped(0x8100, prog) + b"G 8100\r"
    tx, _ = run(typed)
    check_eq(tx, transcript(lpair(0x8100, prog), (b"G 8100", b"HI")),
             "HI printed through the monitor's own putc")


def test_go_to_a_halt_halts():
    print("G to a program that HALTs stops the machine")
    prog = ram_prog("""
          LDAI  0x3C
          OUT
          HALT
    """)
    typed = ltyped(0x8100, prog) + b"G 8100\rD 8100\r"
    tx, st = run(typed)
    check_eq(tx, transcript(lpair(0x8100, prog)) + b"G 8100\r\n",
             "nothing after G: the machine halted")
    check(st["halted"], "halted")
    check_eq(st["out"], 0x3C, "the program ran to its HALT")


def test_go_takes_no_value():
    print("G addr,val and bare G are refused")
    tx, st = run(b"G 8100,1\rG\r")
    check_eq(tx, transcript((b"G 8100,1", b"?"), (b"G", b"?")),
             "`?` and nothing jumps")
    check(st["out"] in (None, 0xFF), "nothing ran")

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
