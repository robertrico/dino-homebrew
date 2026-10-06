#!/usr/bin/env python3
"""Host tests for asm/imon.asm -- the interrupt-driven monitor -- and for
the two oracle features it needs.

THE ORACLE ADDITIONS ARE A TEST DOUBLE, NOT A UART MODEL (PHASE_G.md
SECTION 5 still holds):

    serial_gap=N   the script's bytes ARRIVE one per N instruction
                   boundaries instead of all at once. A stand-in for
                   typing/pasting at 9600 baud (~250 boundaries a character
                   at 1.024 MHz). Without it nothing changes.
    RX level       ~{IRQ} is asserted at a boundary while IER bit 0 (RDA)
                   is set and a script byte is waiting. That is the 16550's
                   received-data interrupt as a LEVEL, which is what the
                   datasheet says it is (8.4: cleared by reading RBR).

THE ANSWER KEY IS THE TRANSCRIPT, as in test_monitor.py: imon must answer
every line exactly as the polling monitor does. Only the banner differs, so
the seated ROM names itself.

Run: python3 test_imon.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ASMDIR = os.path.join(HERE, "..", "..", "asm")
SRC = os.path.join(ASMDIR, "imon.asm")
SPIN = os.path.join(ASMDIR, "ram", "spin.asm")

BANNER = b"DINO IMON\r\n"
PROMPT = b"> "
BREAK = b"^C\r\n"
GAP = 250                         # boundaries per character, ~9600 baud
VEC = 0x9090


def _img(text):
    r = asm.assemble_text(text)
    return pg.build_image_from_bytes(r.code, r.origin), r.labels


def _src():
    with open(SRC) as f:
        return f.read()


def run(typed, text=None, **kw):
    img, _ = _img(text if text is not None else _src())
    kw.setdefault("max_steps", 400_000)
    kw.setdefault("serial_gap", GAP)
    return pg.simulate(None, image=img, serial_in=typed, **kw)


def transcript(*lines, banner=BANNER):
    out = banner + PROMPT
    for typed, reply in lines:
        out += typed + b"\r\n"
        if reply is not None:
            out += reply + b"\r\n"
        out += PROMPT
    return out


def _fast_spin():
    """spin.asm with its delay cut to a few boundaries, so a host run sees
    it count in thousands of steps instead of ~65k a count."""
    with open(SPIN) as f:
        t = f.read()
    t = t.replace("OUTER:    .equ  128", "OUTER:    .equ  2")
    return t.replace("INNER:    .equ  0xFF", "INNER:    .equ  3")


def _hexload(path=None, text=None):
    """The L line and payload dinoload would send for a RAM program."""
    if text is None:
        with open(path) as f:
            text = f.read()
    r = asm.assemble_text(text)
    body = bytes(r.code)
    return r.origin, body, (b"L %X,%X\r" % (r.origin, len(body))
                            + body.hex().upper().encode() + b"\r")


# ---- the oracle additions -----------------------------------------------

_RDA_PROBE = """
          .org  0x0000
          LDAI  0xFF
          OUT
          LXISP 0x80FF
          MVI   0x9090, 0x31
          MVI   0x9091, <isr
          MVI   0x9092, >isr
          LDAI  0x01            ; IER = RDA only
          STA   0x4801
          EI
spin:     JMP   spin
isr:      LDA   0x4800          ; RBR: the read clears the request
          OUT
          IRET
"""


def test_oracle_rx_level_interrupts_and_rbr_read_clears_it():
    img, _ = _img(_RDA_PROBE)
    st = pg.simulate(None, image=img, serial_in=b"AB", serial_gap=50,
                     max_steps=3000)
    assert st["outs"] == [0xFF, 0x41, 0x42], st["outs"]
    assert len(st["ints"]) == 2, st["ints"]


def test_oracle_without_rda_enabled_no_interrupt():
    img, _ = _img(_RDA_PROBE.replace("LDAI  0x01            ; IER",
                                     "LDAI  0x00            ; IER"))
    st = pg.simulate(None, image=img, serial_in=b"AB", serial_gap=50,
                     max_steps=3000)
    assert st["ints"] == [] and st["outs"] == [0xFF], st


def test_oracle_gap_holds_bytes_back():
    """With a gap, nothing is waiting until the gap has passed."""
    img, _ = _img(_RDA_PROBE)
    st = pg.simulate(None, image=img, serial_in=b"A", serial_gap=500,
                     max_steps=200)
    assert st["outs"] == [0xFF], st["outs"]


# ---- imon answers like the monitor ----------------------------------------

def test_banner_names_the_rom_then_prompt():
    st = run(b"")
    assert st["tx"] == BANNER + PROMPT, st["tx"]
    assert not st["halted"]


def test_dump_write_and_bad_line_like_the_monitor():
    st = run(b"W 8044,A5\rD 8044\rD 0\rQ 1\r")
    assert st["tx"] == transcript((b"W 8044,A5", b"0xA5"),
                                  (b"D 8044", b"0xA5"),
                                  (b"D 0", b"0x11"),
                                  (b"Q 1", b"?")), st["tx"]


def test_load_and_go_hello_comes_back():
    org, body, line = _hexload(os.path.join(ASMDIR, "ram", "hello.asm"))
    st = run(line + b"G %X\r" % org, max_steps=600_000)
    assert 0x5A in st["outs"], st["outs"]
    assert st["tx"].endswith(PROMPT) and b"?" not in st["tx"], st["tx"]


def test_a_paste_longer_than_the_ring_is_not_dropped():
    """64 payload bytes = 128 hex characters through a 16-byte ring."""
    body = bytes(range(0x10, 0x50))
    line = b"L 8200,40\r" + body.hex().upper().encode() + b"\r"
    st = run(line + b"D 823F\r", max_steps=900_000)
    assert st["tx"].endswith(b"D 823F\r\n0x4F\r\n" + PROMPT), st["tx"][-60:]
    assert b"?" not in st["tx"], st["tx"]


# ---- the ROM entry points loaded programs call ------------------------------

def test_putc_puthex_puts_crlf_keep_the_monitors_addresses():
    _, mon = _img(open(os.path.join(ASMDIR, "monitor.asm")).read())
    _, imon = _img(_src())
    for name in ("putc", "puthex", "puts", "crlf"):
        assert imon[name] == mon[name], (name, hex(imon[name]),
                                         hex(mon[name]))


# ---- Ctrl-C ------------------------------------------------------------------

def test_ctrl_c_breaks_a_running_program_back_to_the_prompt():
    org, body, line = _hexload(text=_fast_spin())
    st = run(line + b"G %X\r" % org + b"\x03" + b"D 0\r",
             max_steps=900_000)
    tx = st["tx"]
    assert BREAK + PROMPT in tx, tx[-60:]
    assert tx.endswith(b"D 0\r\n0x11\r\n" + PROMPT), tx[-60:]
    assert len(set(st["outs"])) > 3, "spin never counted on OB"


def test_ctrl_c_mirror_a_handler_that_ignores_it_never_comes_back():
    org, body, line = _hexload(text=_fast_spin())
    text = _src().replace("CPI   0x03", "CPI   0xEE")   # break key never seen
    st = run(line + b"G %X\r" % org + b"\x03" + b"D 0\r", text=text,
             max_steps=900_000)
    assert BREAK not in st["tx"], st["tx"][-60:]


def test_ctrl_c_at_the_prompt_is_harmless():
    st = run(b"\x03D 0\r")
    assert st["tx"].endswith(b"D 0\r\n0x11\r\n" + PROMPT), st["tx"]


def test_the_prompt_replants_the_vector():
    """A G program that points 0x9090 elsewhere gets imon's back at RET."""
    prog = """
          .org  0x8100
          MVI   0x9091, 0x00
          MVI   0x9092, 0x00
          RET
"""
    r = asm.assemble_text(prog)
    body = bytes(r.code)
    line = (b"L 8100,%X\r" % len(body) + body.hex().upper().encode()
            + b"\r")
    st = run(line + b"G 8100\rD 9091\rD 9092\r", max_steps=900_000)
    _, lab = _img(_src())
    want_lo = b"0x%02X" % (lab["isr"] & 0xFF)
    want_hi = b"0x%02X" % (lab["isr"] >> 8)
    assert (b"D 9091\r\n" + want_lo) in st["tx"], st["tx"][-80:]
    assert (b"D 9092\r\n" + want_hi) in st["tx"], st["tx"][-80:]


_HALTER = """
          .org  0x8100
          LDAI  0x3C
          OUT
          HALT
          LDAI  0x77
          OUT
          RET
"""


def _halter_line():
    r = asm.assemble_text(_HALTER)
    body = bytes(r.code)
    return (b"L 8100,%X\r" % len(body) + body.hex().upper().encode()
            + b"\r")


def test_ctrl_c_brings_a_halted_program_back_to_the_prompt():
    st = run(_halter_line() + b"G 8100\r\x03D 0\r", max_steps=900_000)
    assert st["outs"][-1] == 0x3C and not st["halted"], st["outs"]
    assert st["tx"].endswith(b"G 8100\r\n" + BREAK + PROMPT
                             + b"D 0\r\n0x11\r\n" + PROMPT), st["tx"][-60:]


def test_any_other_key_resumes_after_the_halt_and_is_typed_ahead():
    st = run(_halter_line() + b"G 8100\rZ\r", max_steps=900_000)
    assert st["outs"][-2:] == [0x3C, 0x77], st["outs"]
    assert st["tx"].endswith(b"G 8100\r\n" + PROMPT + b"Z\r\n?\r\n"
                             + PROMPT), st["tx"][-60:]


# ---- spin.asm, the bench witness ------------------------------------------

def test_spin_counts_on_ob_and_never_returns():
    text = _fast_spin()
    assert asm.assemble_text(text).origin == 0x8100
    # the same code run from ROM: it is position-independent apart from its
    # own labels, which the assembler re-resolves at the new origin
    img, _ = _img(text.replace(".org  0x8100", ".org  0x0000"))
    st = pg.simulate(None, image=img, max_steps=20_000)
    assert not st["halted"]
    assert st["outs"][:4] == [1, 2, 3, 4], st["outs"][:10]
    assert BREAK not in (st.get("tx") or b"")


if __name__ == "__main__":
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"  ok   {_name}")
        except Exception as _e:                   # noqa: BLE001
            _failed.append((_name, _e))
            print(f"  FAIL {_name}: {type(_e).__name__}: {str(_e)[:200]}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_imon")
