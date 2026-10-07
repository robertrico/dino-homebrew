#!/usr/bin/env python3
"""SCELBAL on DINO, end to end: the U24 image (imon + translated SCELBAL)
in simulate(), typed at like the bench, against the ORIGINAL on i8008.

PHASE_BASIC step 5. The session is the bench's: imon's prompt, `G 0A00`
(cold start: fresh data pages), then BASIC. Everything the machine sends
after the G line's echo must equal, byte for byte, what scelbal_ref.py's
8008 prints for the same keystrokes. Nothing here says what BASIC should
print; the 8008 says it.

Run: python3 test_scelbal_dino.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402
import scelbal_ref as ref                                     # noqa: E402
import scelbal_xlate as x                                     # noqa: E402

GAP = 250                       # imon: boundaries per typed character
QUIET = 2_000_000               # idle = this many boundaries of silence at
                                # getc. SQR(16) computes >400K in silence
_IMG = {}


ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
BIN = os.path.join(ROOT, "roms", "PROG_basic.bin")


def image():
    """The U24 image, assembled from the GENERATED asm/basic.asm -- the
    file `make assemble-basic` burns from, not a test-only build."""
    if "img" not in _IMG:
        r = asm.assemble_text(open(x.OUT).read())
        assert r.origin == 0
        _IMG["img"] = pg.build_image_from_bytes(r.code, 0, fill=r.fill)
        _IMG["r"] = r
    return _IMG["img"]


def dino_session(keys, max_steps=2_000_000_000, switches=0x00):
    go = b"G %04X\r" % x.CODE
    saved = pg.IDLE_QUIET_ENDS
    pg.IDLE_QUIET_ENDS = QUIET
    try:
        st = pg.simulate(None, image=image(), serial_in=b"\r" + go + keys,
                         switches=switches,
                         max_steps=max_steps, serial_gap=GAP,
                         serial_echo_paced=True)
    finally:
        pg.IDLE_QUIET_ENDS = saved
    tx = st["tx"]
    echo = go[:-1] + b"\r\n"
    i = tx.rfind(echo)
    assert i >= 0, f"imon never echoed the G line: {tx[-200:]!r}"
    return tx[i + len(echo):].decode("ascii", "replace"), st


IMON_BOOT_OUTS = 1              # imon.asm writes OB once before its prompt


def same(keys, switches=0x00):
    leds = []
    want = ref.session(keys, switches=switches, leds=leds, dmem={})
    got, st = dino_session(keys, switches=switches)
    assert got == want, (f"\n--- 8008 ---\n{want!r}\n--- DINO ---\n{got!r}"
                         f"\nidle={st.get('idle')} halted={st['halted']}")
    assert st["outs"][IMON_BOOT_OUTS:] == leds, (st["outs"], leds)


def test_generated_file_is_current():
    """asm/basic.asm is regenerated, never edited: an imon change or a
    translator change without `python3 scelbal_xlate.py` fails here."""
    assert open(x.OUT).read() == x.basic_asm()


def test_burn_file_matches_source():
    with open(BIN, "rb") as f:
        assert f.read() == image(), "roms/PROG_basic.bin is stale: make assemble-basic"


def test_fits_u24_and_imon_untouched():
    image()
    r = _IMG["r"]
    assert len(r.code) <= x.ROM_END, f"{len(r.code)} bytes > 16K window"
    mon = asm.assemble_text(open(x.IMON).read())
    assert len(mon.code) <= x.IMON_END
    assert r.code[:len(mon.code)] == mon.code
    for name in ("putc", "puthex", "crlf", "puts", "getc", "isr"):
        assert r.labels[name] == mon.labels[name], name


def test_ctrl_c_then_warm_start_keeps_the_program():
    """imon's isr takes Ctrl-C from BASIC back to the prompt; G warm (CODE+3)
    re-enters at EXEC with the program intact. No 8008 counterpart: the
    break is imon's."""
    # SCELBAL prints CRLF BEFORE it stores the line, so echo pacing alone
    # would release Ctrl-C mid-store (which abandons that line, as a break
    # should). The second empty line is read only after line 10 is stored.
    keys = (b"SCR\r10 PRINT 7\r\r\r\x03" + b"G %04X\r" % (x.CODE + 3)
            + b"LIST\r")
    got, st = dino_session(keys)
    tail = got.split("^C", 1)
    assert len(tail) == 2, repr(got)
    assert "10 PRINT 7" in tail[1].split("LIST", 1)[1], repr(got)


def test_banner():
    same(b"")


def test_print_arithmetic():
    same(b"PRINT 2+3\r")


def test_print_float():
    same(b"PRINT 2/3\r")


def test_program_for_loop_and_list():
    same(b"SCR\r10 FOR I=1 TO 3\r20 PRINT I*I\r30 NEXT I\r40 END\rRUN\r"
         b"LIST\r")


def test_input():
    same(b"SCR\r10 INPUT A\r20 PRINT A+1\rRUN\r41\r")


def test_arrays_functions_gosub():
    same(b"SCR\r10 DIM A(5)\r20 FOR I=1 TO 5\r30 A(I)=I*2.5\r40 NEXT I\r"
         b"50 PRINT A(3),SQR(16),INT(-2.5)\r60 IF A(2)<6 THEN 80\r"
         b"70 PRINT \"NO\"\r80 GOSUB 100\r90 END\r100 PRINT \"SUB\";\r"
         b"110 RETURN\rRUN\r")


def test_udf_reads_sw1_and_drives_the_leds():
    """asm/scelbal/udf.as8: UDF(0) = SW1, UDF(N) = N-1 to OB."""
    same(b"PRINT UDF(0)\rX=UDF(256)\rPRINT UDF(43)\r"
         b"SCR\r10 FOR I=1 TO 4\r20 X=UDF(I*16)\r30 NEXT I\rRUN\r",
         switches=0x5A)


# Aimed at the routines the first sessions never ran (coverage 80%,
# 2026-10-06): relations, REM/LET, ^, STEP -n, SGN ABS TAB CHR RND,
# E-notation in and out, multi-array DIM, line delete/replace, rubout,
# and the parser's error exits. The 8008 decides what is right.
CORPUS = [
    b"SCR\r10 REM HI\r20 LET A=5\r30 IF A>4 THEN 50\r40 PRINT 1\r"
    b"50 IF A<=5 THEN 70\r60 PRINT 2\r70 IF A>=6 THEN 90\r"
    b"80 IF A=5 THEN 100\r90 PRINT 3\r100 IF A<>4 THEN 120\r110 PRINT 4\r"
    b"120 PRINT SGN(-3),ABS(-7),2^10,2^-2\r130 FOR J=10 TO 1 STEP -3\r"
    b"140 PRINT J;\r150 NEXT J\r160 PRINT TAB(5);CHR(65)\r"
    b"170 PRINT 1E10,1.5E-5,-0.001,123456789\r180 DIM B(3),C(2)\r"
    b"190 B(2)=7\r200 C(1)=B(2)*2\r210 PRINT C(1),RND(1),RND(1)\rRUN\r",
    b"SCR\r10 PRINT 1\r20 PRINT 2\r30 PRINT 3\r10\rLIST\r"
    b"20 PRINT 22\rLIST\rRUN\r",
    b"PRZ\x7fINT 5\rPRINT (2\rPRINT \"AB\rX=\rPRINT 1/0\r"
    b"PRINT 3.25E2*-4\rPRINT -(2-5)\r",
    b"SCR\r10 INPUT A\r20 INPUT B\r30 PRINT A*B,A/B,A-B\r"
    b"40 IF A<B THEN 10\rRUN\r3\r-4.5\r1E3\r0.25\r",
    b"SCR\r10 RETURN\rRUN\rSCR\r10 NEXT I\rRUN\rSCR\r10 PRINT SQR(-1)\r"
    b"RUN\rSCR\r10 DIM A(300)\rRUN\rSCR\r10 GOSUB 99\rRUN\r"
    b"PRINT RND(0),RND(2),RND(-1)\rPRINT CHR(66);TAB(3);\"X\"\r"
    b"PRINT 1E-30,1E30,0.000001,999999.9\rLET=\rIF 1 THEN\r",
]


def test_corpus_relations_functions_formats():
    same(CORPUS[0])


def test_corpus_line_editing():
    same(CORPUS[1])


def test_corpus_rubout_and_parse_errors():
    same(CORPUS[2])


def test_corpus_input_loop():
    same(CORPUS[3])


def test_corpus_error_exits_rnd_extremes():
    same(CORPUS[4])


def test_peek_poke():
    """peekpoke.as8. 0xF000 up is RAM no part of the port uses, so the
    reference's stand-in memory and DINO's RAM must agree; 16384 is SW1.
    Old keywords and functions still parse (the tables moved)."""
    same(b"PRINT PEEK(16384)\rPOKE 61440,77\rPRINT PEEK(61440)\r"
         b"SCR\r10 FOR I=0 TO 3\r20 POKE 61441+I,I*3+1\r30 NEXT I\r"
         b"40 S=0\r50 FOR J=61441 TO 61444\r60 S=S+PEEK(J)\r70 NEXT J\r"
         b"80 PRINT S,INT(7.5),ABS(-2),SGN(-9)\r90 GOSUB 200\r100 END\r"
         b"200 IF PEEK(61442)=4 THEN 220\r210 PRINT \"BAD\"\r"
         b"220 RETURN\rRUN\rPOKE 5\rLIST\r",
         switches=0x1C)


def test_errors_do_not_leak_the_stack():
    """SCELBAL's error exits and END JMP to EXEC from inside calls. On the
    8008 the circular stack forgets them; DINO's RAM stack would GROW, and
    a few hundred errors later run down into the cells at 0x81xx. EXEC
    resets SP, so SP at the prompt is the same after 1 error and after 12."""
    one = dino_session(b"X=\r")[1]["sp"]
    many = dino_session(b"X=\r" * 12 + b"SCR\r10 END\rRUN\rRUN\rRUN\r")[1]["sp"]
    assert one == many, (hex(one), hex(many))


def test_errors():
    same(b"PRUNT 1\rSCR\r10 GOTO 50\rRUN\r")


# ---- runner: ENUMERATED (test_suite_reachability.py) -------------------
if __name__ == "__main__":
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"  ok   {_name}", flush=True)
        except Exception as _e:                   # noqa: BLE001
            _failed.append((_name, _e))
            print(f"  FAIL {_name}: {type(_e).__name__}: {_e}", flush=True)
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_scelbal_dino")
