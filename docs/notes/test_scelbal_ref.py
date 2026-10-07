#!/usr/bin/env python3
"""Host tests for scelbal_ref.py -- original SCELBAL, run on i8008.py.

PHASE_BASIC step 3. These pin that the REFERENCE works: the 8008 image
assembled from upstream source, with CINP/CPRINT hooked to a scripted
terminal, behaves as a BASIC. The DINO port is later compared against
whatever this prints, byte for byte -- so if this is wrong, everything
downstream is checked against a wrong answer.

A cold image needs `SCR` before program lines (FACT, 2026-10-06: without
it LIST loops at 0x034E and line entry overflows the 8008 stack) -- the
program-buffer pointers are set by SCR, not by the load.

Run: python3 test_scelbal_ref.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scelbal_ref as ref                                     # noqa: E402


def test_banner_is_ready():
    out = ref.session(b"")
    assert "READY" in out, repr(out)


def test_print_arithmetic():
    out = ref.session(b"PRINT 2+3\r")
    assert "5" in out.split("PRINT 2+3", 1)[1], repr(out)


def test_print_fraction_shows_float():
    out = ref.session(b"PRINT 2/3\r")
    tail = out.split("PRINT 2/3", 1)[1]
    assert ".666" in tail, repr(out)


def test_program_run_for_loop():
    prog = b"SCR\r10 FOR I=1 TO 3\r20 PRINT I*I\r30 NEXT I\r40 END\rRUN\r"
    out = ref.session(prog)
    tail = out.split("RUN", 1)[1]
    nums = [t for t in tail.split() if t.replace(".", "").isdigit()]
    assert nums[:3] == ["1.0", "4.0", "9.0"], repr(out)


def test_list_echoes_program():
    out = ref.session(b"SCR\r10 PRINT 7\rLIST\r")
    assert out.count("10 PRINT 7") >= 2, repr(out)


def test_input_statement_reads_terminal():
    out = ref.session(b"SCR\r10 INPUT A\r20 PRINT A+1\rRUN\r41\r")
    assert "42.0" in out.split("RUN", 1)[1], repr(out)


def test_syntax_error_reported():
    out = ref.session(b"PRUNT 1\r")
    assert out.count("READY") >= 2, repr(out)


def test_udf_zero_reads_the_switches():
    """DINO patch (asm/scelbal/udf.as8): UDF(0) is SW1's byte."""
    out = ref.session(b"PRINT UDF(0)\r", switches=0x5A)
    assert "90.0" in out.split("PRINT UDF(0)", 1)[1], repr(out)


def test_udf_n_writes_the_leds():
    leds = []
    out = ref.session(b"PRINT UDF(6)\rX=UDF(256)\rX=UDF(1)\r", leds=leds)
    assert leds == [5, 255, 0], leds
    assert "5.0" in out.split("PRINT UDF(6)", 1)[1], repr(out)


def test_upstream_untouched_patch_applied():
    import as8
    text = ref.source()
    assert "UDEFX:\tJMP UDF8" in text
    with open(ref.SRC) as f:
        assert "UDEFX:\tHLT" in f.read()


def test_peek_reads_dino_addresses():
    """asm/scelbal/peekpoke.as8. PEEK(16384) is SW1 (card zero)."""
    out = ref.session(b"PRINT PEEK(16384)\r", switches=0x1C)
    assert "28.0" in out.split("PRINT PEEK(16384)", 1)[1], repr(out)


def test_poke_then_peek_round_trip():
    dmem = {}
    out = ref.session(b"POKE 61440,77\rPRINT PEEK(61440)\r"
                      b"SCR\r10 FOR I=0 TO 2\r20 POKE 61441+I,I*3\r"
                      b"30 NEXT I\r40 PRINT PEEK(61443)\rRUN\r", dmem=dmem)
    assert dmem == {0xF000: 77, 0xF001: 0, 0xF002: 3, 0xF003: 6}, dmem
    tail = out.split("PRINT PEEK(61440)", 1)[1]
    assert "77.0" in tail and "6.0" in tail.split("RUN", 1)[1], repr(out)


def test_poke_without_comma_is_an_error():
    out = ref.session(b"POKE 5\r")
    assert "PK" in out.split("POKE 5", 1)[1], repr(out)


def test_old_keywords_and_functions_unchanged():
    out = ref.session(b"SCR\r10 X=INT(7.5)+SGN(-2)+ABS(-3)\r20 PRINT X\r"
                      b"30 END\rRUN\r")
    assert " 9.0" in out.split("RUN", 1)[1], repr(out)


PROGRAMS = [
    b"PRINT 2/3\r",
    b"SCR\r10 FOR I=1 TO 3\r20 PRINT I*I\r30 NEXT I\r40 END\rRUN\rLIST\r",
    b"SCR\r10 INPUT A\r20 PRINT A+1\rRUN\r41\r",
    b"SCR\r10 DIM A(5)\r20 FOR I=1 TO 5\r30 A(I)=I*2.5\r40 NEXT I\r"
    b"50 PRINT A(3),SQR(16),INT(-2.5)\r60 IF A(2)<6 THEN 80\r"
    b"70 PRINT \"NO\"\r80 GOSUB 100\r90 END\r100 PRINT \"SUB\";\r"
    b"110 RETURN\rRUN\r",
    b"PRINT UDF(0)\rX=UDF(9)\r",
]


def test_code_bytes_are_never_data():
    """The port RELOCATES code (DINO code is not at 0x8000 + its 8008
    address), so SCELBAL must never read or write an instruction byte
    through M. Self-modifying code or a table inside code would break the
    port silently; this watches every M access in every session."""
    import as8
    items = as8.parse(ref.source())
    code = {a for it in items if it.kind == "code"
            for a in range(it.addr, it.addr + it.size)}
    for prog in PROGRAMS:
        seen = set()
        ref.session(prog, m_seen=seen)
        bad = sorted(seen & code)
        assert not bad, f"{prog!r}: M touched code at {[hex(a) for a in bad[:8]]}"


# ---- runner: ENUMERATED (test_suite_reachability.py) -------------------
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
            print(f"  FAIL {_name}: {type(_e).__name__}: {_e}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_scelbal_ref")
