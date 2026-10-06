#!/usr/bin/env python3
"""Host tests for ADC / SBB / ACI / SBI -- carry into the ALU (PHASE_F 3.3).

Rico, 2026-10-06. The '157 is in copper as U76 on the ALU board (drawn
as U76; PHASE_F called it U80 before the INT block took that number):

    S   <- CW16 ~{CIN_SEL}    U23.11
    I0a <- FLAG_C             U49.2      CW16 = 0: carry from the flag
    I1a <- ALU_CIN            U50.13     CW16 = 1: NAND(SA1, SA0), every old row
    Za  -> ALU_CN             U38.15

Bench 2026-10-06 with the old microcode (CW16 = 1 everywhere): isa 0xB4,
isasoak 0x00 x10 -- the mux is inert.

ADC = A + B + FLAG_C and SBB = A - B - (1 - FLAG_C): both want CN = FLAG_C
directly, because CN is a true carry on ADD and a not-borrow on SUB.

Two halves:
  microcode  -- the four new opcodes, CW16 only where asked, no old row moved
  oracle     -- simulate() as the answer key: 16-bit add and subtract

Run: python3 test_carry.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import microcode_gen as g                                    # noqa: E402
from microcode_gen import (OPCODES, INSTRUCTIONS, SA, SETTLE,  # noqa: E402
                           CIN_SEL_N, word, check_word, BuildError)
import progrom_gen as p                                      # noqa: E402
import asm                                                   # noqa: E402

NEW = {"ADC": 0x96, "SBB": 0x97, "ACI": 0x98, "SBI": 0x99}


def _cin_from_flag(w):
    return not (w & CIN_SEL_N)


# ==== microcode ==========================================================

def test_opcodes_assigned():
    for name, op in NEW.items():
        assert OPCODES.get(name) == op, f"{name} should be {op:#04x}"


def test_every_existing_row_is_byte_identical():
    """CRC over the 252 opcode blocks that are not 0x96-0x99, pinned from
    the generator BEFORE any carry row existed -- the image in the sockets,
    U9 0xEE1F / U15 0x1DE7 / U23 0x0C0A. If this moves, an old instruction
    changed: a burn nobody asked for."""
    w = g.build_real()
    b = bytearray()
    for op in range(256):
        if 0x96 <= op <= 0x99:
            continue
        for x in w[op * 16:op * 16 + 16]:
            b += x.to_bytes(3, "little")
    assert g.crc16(bytes(b)) == 0x103C, hex(g.crc16(bytes(b)))


def test_adc_sbb_are_add_sub_with_the_carry_from_the_flag():
    for name, sa in (("ADC", "ADD"), ("SBB", "SUB")):
        nbytes, rows = INSTRUCTIONS[name]
        assert nbytes == 1
        assert rows == [word(end=True, sa=sa, src="ALU", dst="REG_A",
                             cin_from_flag_c=True)], name


def test_aci_sbi_are_adi_sui_with_the_carry_on_the_alu_row_only():
    """The operand fetch (src=ROM) holds the flags (U48 selects the ALU's
    flags only while ~{ALU_OUT} is low), so the carry ADI-shaped rows read
    is the one the previous instruction left."""
    for name, base in (("ACI", "ADI"), ("SBI", "SUI")):
        nbytes, rows = INSTRUCTIONS[name]
        bn, brows = INSTRUCTIONS[base]
        assert nbytes == bn == 2
        assert len(rows) == len(brows) == 3
        assert rows[:2] == brows[:2], f"{name} fetch/settle differ from {base}"
        assert rows[2] == brows[2] & ~CIN_SEL_N, name


def test_cw16_is_low_only_on_the_four_carry_alu_rows():
    w = g.build_real()
    low = sorted((a >> 4, a & 0xF) for a, x in enumerate(w)
                 if _cin_from_flag(x))
    want = sorted([(0x96, 1), (0x97, 1), (0x98, 3), (0x99, 3)])
    assert low == want, [(hex(o), t) for o, t in low]


def test_a_carry_row_on_a_logic_function_is_refused():
    """CN means nothing to the '382's logic codes. A row that asks for the
    flag carry on AND encodes cleanly and does nothing: refuse it."""
    for sa in ("AND", "OR", "XOR", "CLR"):
        try:
            check_word(0x961, word(sa=sa, src="ALU", dst="REG_A",
                                   cin_from_flag_c=True))
        except BuildError as e:
            assert "carry" in str(e), e
            continue
        raise AssertionError(f"cin_from_flag_c on {sa} must be refused")


def test_a_carry_row_without_the_alu_as_source_is_refused():
    try:
        check_word(0x961, word(src="REG_B", dst="REG_A",
                               cin_from_flag_c=True))
    except BuildError as e:
        assert "carry" in str(e), e
        return
    raise AssertionError("cin_from_flag_c without src=ALU must be refused")


def test_image_builds_and_passes_check_table():
    g.build_real()


# ==== assembler ==========================================================

def test_assembler_knows_the_four():
    r = asm.assemble_text("ADC\nSBB\nACI 0x05\nSBI 0xA0\n")
    assert bytes(r.code) == bytes([0x96, 0x97, 0x98, 0x05, 0x99, 0xA0])


# ==== oracle =============================================================

def _run(text, **kw):
    r = asm.assemble_text(text)
    return p.simulate([], image=bytes(r.code), **kw)


def test_16bit_add_carries_into_the_high_byte():
    # 0x12FF + 0x0101 = 0x1400
    st = _run("""
          LDAI 0xFF
          LDBI 0x01
          ADD
          OUT
          LDAI 0x12
          LDBI 0x01
          ADC
          OUT
          HALT
    """)
    assert st["outs"] == [0x00, 0x14], [hex(x) for x in st["outs"]]
    assert st["flag_c"] == 0


def test_adc_with_carry_clear_is_add():
    st = _run("""
          LDAI 0x01
          LDBI 0x01
          ADD
          LDAI 0x12
          LDBI 0x01
          ADC
          OUT
          HALT
    """)
    assert st["outs"] == [0x13]


def test_adc_carries_out_and_sets_z():
    # 0xFF + 0x00 + 1 = 0x100
    st = _run("""
          LDAI 0xFF
          LDBI 0x01
          ADD
          LDAI 0xFF
          LDBI 0x00
          ADC
          OUT
          HALT
    """)
    assert st["outs"] == [0x00]
    assert st["flag_c"] == 1 and st["flag_z"] == 1


def test_16bit_subtract_borrows_from_the_high_byte():
    # 0x1200 - 0x0001 = 0x11FF. SUB's FLAG_C is NOT-borrow: 0 here.
    st = _run("""
          LDAI 0x00
          LDBI 0x01
          SUB
          OUT
          LDAI 0x12
          LDBI 0x00
          SBB
          OUT
          HALT
    """)
    assert st["outs"] == [0xFF, 0x11], [hex(x) for x in st["outs"]]
    assert st["flag_c"] == 1


def test_sbb_with_no_borrow_is_sub():
    st = _run("""
          LDAI 0x05
          LDBI 0x01
          SUB
          LDAI 0x12
          LDBI 0x02
          SBB
          OUT
          HALT
    """)
    assert st["outs"] == [0x10]


def test_sbb_borrows_out():
    # 0x00 - 0x00 - 1 = 0xFF, borrow -> FLAG_C 0
    st = _run("""
          LDAI 0x00
          LDBI 0x01
          SUB
          LDAI 0x00
          LDBI 0x00
          SBB
          OUT
          HALT
    """)
    assert st["outs"] == [0xFF]
    assert st["flag_c"] == 0


def test_immediate_forms():
    # 0x34FF + 0x0001 -> 0x3500 ; 0x3500 - 0x0001 -> 0x34FF
    st = _run("""
          LDAI 0xFF
          ADI  0x01
          OUT
          LDAI 0x34
          ACI  0x00
          OUT
          LDAI 0x00
          SUI  0x01
          OUT
          LDAI 0x35
          SBI  0x00
          OUT
          HALT
    """)
    assert st["outs"] == [0x00, 0x35, 0xFF, 0x34], [hex(x) for x in st["outs"]]


def test_adc_after_a_logic_op_is_unoracled():
    """CN+4 after AND is undefined on the '382: the oracle refuses rather
    than guess, exactly as it does for JNC."""
    try:
        _run("""
          LDAI 0x0F
          LDBI 0xF0
          AND
          ADC
          HALT
        """)
    except p.Unoracled:
        return
    raise AssertionError("ADC reading a carry left by AND must be refused")


# ==== the bench image: asm/carry.asm -> PROG_carry =======================
#
# OB 0xAD = every subtest passed on every one of 256 passes. Any other value
# is the id of the first subtest that failed; 0xFF = never finished. Every
# subtest flips the carry across the instruction (in 1 -> out 0, or in 0 ->
# out 1) in at least one case per op, so an ALU that latched its answer
# with the NEW carry instead of the old one is caught.

CARRY_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "asm", "carry.asm")
CARRY_PASS = 0xAD


def _carry_image():
    r = asm.assemble_text(open(CARRY_SRC).read())
    return p.build_image_from_bytes(r.code, r.origin), r


def _carry_run():
    img, _ = _carry_image()
    return p.simulate(None, image=img, max_steps=2_000_000)


def test_carry_image_passes_under_the_oracle():
    st = _carry_run()
    assert st["halted"] and st["out"] == CARRY_PASS, hex(st["out"])


def _mutated(name, rows):
    saved = INSTRUCTIONS[name]
    INSTRUCTIONS[name] = (saved[0], rows)
    try:
        return _carry_run()
    finally:
        INSTRUCTIONS[name] = saved


def test_each_op_without_cw16_fails_the_image():
    """The witness must be able to fail: each op with its CW16 bit set
    back (U76 passing the NAND term) is ADD/SUB/ADI/SUI, and the image
    must say so with a subtest id, not the pass byte."""
    for name in NEW:
        nbytes, rows = INSTRUCTIONS[name]
        st = _mutated(name, [w | CIN_SEL_N for w in rows])
        assert st["halted"] and st["out"] not in (CARRY_PASS, 0xFF), \
            f"{name} without CW16: OB {st['out']:#04x}"


def test_an_inverted_flag_fails_the_image():
    """I0a wired from an inverted carry (or the '382 reading not-borrow the
    other way round) must not pass."""
    real = p._alu_op
    p._alu_op = lambda op, a, b, cin=None: real(
        op, a, b, None if cin is None else cin ^ 1)
    try:
        st = _carry_run()
    finally:
        p._alu_op = real
    assert st["out"] != CARRY_PASS, "an inverted carry passed"


def test_the_burned_microcode_cannot_pass_it():
    """On the 0x0C0A microcode 0x96-0x99 are blank blocks (FETCH, then END).
    Burned in the wrong order, PROG_carry must not read 0xAD."""
    blank = [g.FILL]
    for name in NEW:
        st = _mutated(name, blank)
        assert st["out"] != CARRY_PASS, name


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
    print("OK test_carry")
