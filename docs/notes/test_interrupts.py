#!/usr/bin/env python3
"""Host tests for the maskable interrupt (.git/sdd/PROPOSAL_INT.md).

Rico, 2026-09-25: interrupts go on, DMA does not. Opcodes all in 0x9x,
K = 0x90, vector K:K = 0x9090 in RAM; PUSHF/POPF in.

Two halves:
  microcode  -- the new rows, and the guard that no existing row moved
  oracle     -- simulate(irq_at=...) as the answer key for the bench images

Run: python3 test_interrupts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import microcode_gen as g                                    # noqa: E402
from microcode_gen import (OPCODES, INSTRUCTIONS, SRC, DST, MISC,  # noqa: E402
                           FETCH, END, PC_UP, MUX_PC, _fields)
import progrom_gen as p                                      # noqa: E402
import asm                                                   # noqa: E402

NEW = {"INT": 0x90, "IRET": 0x91, "EI": 0x92, "DI": 0x93,
       "PUSHF": 0x94, "POPF": 0x95}


def _rows(name):
    return INSTRUCTIONS[name][1]


def _decoded(name):
    return [_fields(w) for w in _rows(name)]


# ==== microcode ==========================================================

def test_opcodes_assigned():
    for name, op in NEW.items():
        assert OPCODES.get(name) == op, f"{name} should be {op:#04x}"


def test_new_decoder_codes_are_the_free_outputs():
    # netlist-extracted 2026-09-25: U70 O4/O5 (pins 11/10) and U71 O2-O4
    # (pins 13/12/11) are NC. Bank-1 codes 12/13 and 10/11/12.
    assert SRC["KONST"] == 12 and SRC["FLAGS"] == 13
    assert DST["FLAGS"] == 10 and DST["IE_SET"] == 11 and DST["IE_CLR"] == 12


def test_every_existing_row_is_byte_identical():
    """R7. CRC over the 250 opcode blocks that are not 0x90-0x95, pinned
    from the generator BEFORE any interrupt row existed -- the image whose
    chips are U9 0xC52B / U15 0xDCD1 / U23 0xCB8E. (The sockets carry U15
    0x45F9, the 09-08 OUT settle, which never reached the generator.) If
    this moves, an old instruction changed: a burn nobody asked for."""
    w = g.build_real()
    b = bytearray()
    for op in range(256):
        if 0x90 <= op <= 0x95:
            continue
        for x in w[op * 16:op * 16 + 16]:
            b += x.to_bytes(3, "little")
    assert g.crc16(bytes(b)) == 0x8007, hex(g.crc16(bytes(b)))


def test_konst_is_the_int_opcode_and_the_vector_is_k_k():
    assert g.KONST == OPCODES["INT"] == 0x90
    assert g.INT_VECTOR == 0x9090
    assert g.INT_VECTOR >= p.RAM_BASE, "vector must be in RAM (soft)"


def test_int_pushes_like_call_then_loads_the_vector():
    rows = _rows("INT")
    call = _rows("CALL")
    # the two pushes are CALL's, except IE_CLR rides on the first SP_DOWN
    d = _decoded("INT")
    for t in range(8):
        cm, cs, cd = _fields(call[t])
        m, s, dd = d[t]
        assert (m, s) == (cm, cs), f"INT T{t+1} push differs from CALL"
        if t == 3:
            assert dd == DST["IE_CLR"], "IE must clear inside INT"
        else:
            assert dd == cd
    assert d[8] == (MISC["NONE"], SRC["KONST"], DST["MAR_LO"])
    assert d[9] == (MISC["NONE"], SRC["KONST"], DST["MAR_HI"])
    assert d[10][0] == MISC["PC_LOAD"] and rows[10] & END
    assert len(rows) == 11
    assert not any(w & PC_UP for w in rows), "INT must not move the PC"


def test_ie_clears_before_ints_end():
    d = _decoded("INT")
    first_clr = next(i for i, f in enumerate(d) if f[2] == DST["IE_CLR"])
    assert first_clr < len(d) - 1


def test_iret_never_touches_c():
    """RET parks the return LO byte in C. IRET cannot: C belongs to the
    interrupted program (R3). It parks LO in the PC instead, which IRET
    overwrites anyway."""
    for m, s, d in _decoded("IRET"):
        assert s != SRC["REG_C"] and d != DST["REG_C"]


def test_iret_ends_on_pc_load_with_ie_set_and_no_trailing_pc_up():
    rows = _rows("IRET")
    m, s, d = _fields(rows[-1])
    assert m == MISC["PC_LOAD"] and d == DST["IE_SET"] and rows[-1] & END
    assert not any(w & PC_UP for w in rows)
    assert len(rows) <= 15


def test_ei_di_are_single_rows():
    assert _decoded("EI") == [(MISC["NONE"], SRC["NONE"], DST["IE_SET"])]
    assert _decoded("DI") == [(MISC["NONE"], SRC["NONE"], DST["IE_CLR"])]
    assert _rows("EI")[0] & END and _rows("DI")[0] & END


def test_pushf_is_pusha_shape_from_flags():
    assert [f[1] for f in _decoded("PUSHF")] == \
        [f[1] if f[1] != SRC["REG_A"] else SRC["FLAGS"]
         for f in _decoded("PUSHA")]


def test_popf_reads_twice_before_loading_flags():
    """U49 clocks on ~CLK -- mid T-state, not at the end (P_POPF). The
    first RAM row has no destination and settles the bus; the second
    loads FLAGS from a byte that has been on W for a whole state."""
    d = _decoded("POPF")
    assert d[-2] == (MISC["NONE"], SRC["RAM"], DST["NONE"])
    assert d[-1] == (MISC["NONE"], SRC["RAM"], DST["FLAGS"])
    assert _rows("POPF")[-1] & END


def test_image_builds_and_passes_check_table():
    g.build_real()


# ==== oracle =============================================================

def _run(text, **kw):
    r = asm.assemble_text(text)
    return p.simulate([], image=bytes(r.code), **kw), r.labels


def _prelude(handler="handler"):
    return f"""
          LXISP 0x80FF
          MVI   0x9090, 0x{OPCODES['JMP']:02X}
          MVI   0x9091, <{handler}
          MVI   0x9092, >{handler}
"""


HANDLER_E7 = """
handler:  PUSHA
          LDAI  0xE7
          OUT
          POPA
          IRET
"""

# boundaries: LXISP=1, MVI x3 -> 4, then the program's own instructions.
MAIN = """
          {ei}
          LDAI  0x39
          OUT
next:     LDAI  0x3A
          OUT
          HALT
"""


def test_no_ei_means_no_interrupt():
    st, _ = _run(_prelude() + MAIN.format(ei="NOP") + HANDLER_E7,
                 irq_at={6, 7, 8})
    assert st["outs"] == [0x39, 0x3A] and st["ints"] == []


def test_ei_then_irq_runs_handler_and_returns_to_the_next_fetch():
    st, lab = _run(_prelude() + MAIN.format(ei="EI") + HANDLER_E7,
                   irq_at={7})               # after OUT 0x39
    assert st["outs"] == [0x39, 0xE7, 0x3A]
    assert st["ints"] == [lab["next"]], "pushed PC = the unfetched opcode"
    assert st["halted"]


def test_ei_takes_effect_immediately():
    st, _ = _run(_prelude() + MAIN.format(ei="EI") + HANDLER_E7,
                 irq_at={5})                 # the boundary right after EI
    assert st["outs"][0] == 0xE7


def test_stack_balances_across_an_interrupt():
    quiet, _ = _run(_prelude() + MAIN.format(ei="EI") + HANDLER_E7)
    st, _ = _run(_prelude() + MAIN.format(ei="EI") + HANDLER_E7,
                 irq_at={7})
    assert st["sp"] == quiet["sp"]


def test_iret_reenables_so_a_second_irq_is_taken():
    st, _ = _run(_prelude() + MAIN.format(ei="EI") + HANDLER_E7,
                 irq_at={6, 14})
    # 6: after LDAI 0x39 -> INT 7, JMP (the vector) 8, PUSHA 9, LDAI 10,
    # OUT 11, POPA 12, IRET 13 -> OUT 0x39 14
    assert st["outs"] == [0xE7, 0x39, 0xE7, 0x3A]


def test_ie_is_clear_inside_the_handler():
    # an irq at a boundary INSIDE the handler is ignored
    st, _ = _run(_prelude() + MAIN.format(ei="EI") + HANDLER_E7,
                 irq_at={7, 9})               # 8 = INT, 9 = the vector JMP
    assert len(st["ints"]) == 1


def test_di_masks():
    st, _ = _run(_prelude() + MAIN.format(ei="EI\n          DI")
                 + HANDLER_E7, irq_at={7, 8})
    assert st["ints"] == []


SAVE_RESTORE = """
handler:  PUSHA
          PUSHB
          PUSHC
          {pushf}
          LDAI  0x01
          ORI   0x00            ; Z=0, carry now undefined
          LDBI  0x00
          LDCI  0x00
          {popf}
          POPC
          POPB
          POPA
          IRET
"""

FLAGS_MAIN = """
          EI
          LDBI  0x22
          LDCI  0x33
          LDAI  0x05
          CPI   0x05            ; Z=1, C=1 (A >= 5)
here:     JNZ   bad             ; irq lands before this fetch
          JNC   bad
          LDAI  0x4D
          OUT
          HALT
bad:      LDAI  0xBD
          OUT
          HALT
"""


def test_handler_that_saves_everything_is_invisible():
    text = _prelude() + FLAGS_MAIN + SAVE_RESTORE.format(pushf="PUSHF",
                                                         popf="POPF")
    quiet, _ = _run(text)
    st, lab = _run(text, irq_at={9})
    assert st["ints"] == [lab["here"]]
    assert st["out"] == 0x4D
    for r in ("A", "B", "C", "sp", "flag_z", "flag_c"):
        assert st[r] == quiet[r], f"{r} differs: {st[r]} vs {quiet[r]}"
    assert st["C"] == 0x33


def test_without_popf_the_flags_are_destroyed():
    """Mirror: the save/restore witness must be able to FAIL."""
    st, _ = _run(_prelude() + FLAGS_MAIN
                 + SAVE_RESTORE.format(pushf="NOP", popf="NOP"),
                 irq_at={9})
    assert st["out"] == 0xBD


def test_halt_wakes_and_iret_lands_after_the_halt():
    st, lab = _run(_prelude() + """
          EI
          HALT
after:    LDAI  0x5A
          OUT
          HALT
""" + HANDLER_E7, irq_at={100})
    assert st["outs"] == [0xE7, 0x5A]
    assert st["ints"] == [lab["after"]]


def test_halt_without_ei_stays_halted():
    st, _ = _run(_prelude() + """
          HALT
          LDAI  0x5A
          OUT
          HALT
""" + HANDLER_E7, irq_at={100})
    assert st["outs"] == [] and st["ints"] == []


def test_int_fetched_from_memory_is_refused():
    try:
        p.simulate([], image=bytes([OPCODES["INT"]]))
    except p.BuildError:
        return
    raise AssertionError("fetching 0x90 must raise: INT is injected only")


def test_assemblers_refuse_int():
    try:
        asm.assemble_text("INT")
    except asm.AsmError:
        pass
    else:
        raise AssertionError("asm.py must refuse INT")
    try:
        p.assemble([("INT",)])
    except p.BuildError:
        return
    raise AssertionError("progrom_gen.assemble must refuse INT")


def test_reading_a_pushed_flags_byte_as_data_is_unoracled():
    """The oracle models Z and C, not V and N. A flags byte read back by
    anything but POPF would need all four -- refuse, do not invent."""
    try:
        _run(_prelude() + """
          PUSHF
          POPA
          HALT
""" + HANDLER_E7)
    except p.Unoracled:
        return
    raise AssertionError("POPA of a PUSHF byte must be Unoracled")


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
    print("OK test_interrupts")
