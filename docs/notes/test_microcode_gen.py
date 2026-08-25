#!/usr/bin/env python3
"""Host test for microcode_gen.py. Run: python3 test_microcode_gen.py

Truth sources: dino_session_state.md (CW bit map, microword table, fill
rules), dino_test_bringup_design.md (diag image spec, per-chip CRCs),
dino_design_notes.md (builder assert list).
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROMS = os.path.join(HERE, "..", "..", "roms")
HDR = os.path.join(HERE, "..", "..", "tests", "dino_bringup", "src",
                   "microcode_expect.h")

sys.path.insert(0, HERE)
import microcode_gen as g
from microcode_gen import (INSTRUCTIONS, OPCODES, SRC, DST, SA, word,
                           build_real, check_word)

# ---- CRC16 algorithm (CCITT-FALSE): the one known-answer vector ----
assert g.crc16(b"123456789") == 0x29B1, "crc16 not CRC-16/CCITT-FALSE"

# ---- real image: word-level truth from the session-state table ----
#
# THE WORD IS 24 BITS since 2026-08-10 (U23 carries CW16-23). Every literal
# in this file is the LOW 16 BITS -- the part U9/U15 burn, unchanged since
# the first burn -- so `low()` masks and the third byte gets its own
# assertions below. Written this way on purpose: the 16-bit facts here were
# each paid for, and rewriting them as 24-bit literals would have quietly
# re-derived them instead of preserving them.
def low(w):
    return w & 0xFFFF


def third(w):
    return (w >> 16) & 0xFF


real = g.build_real()
assert len(real) == 4096
# T0 of ALL 256 opcodes = universal fetch (hard rule, session state item 3)
for op in range(256):
    assert low(real[op * 16 + 0]) == 0x600E, f"T0 of opcode {op:#04x} not fetch"
# unused rows = safe-fill END
assert low(real[0x0F5]) == 0x1000, "safe-fill missing (opcode 0x0F, T5)"
assert low(real[0xE31]) == 0x1000, "safe-fill missing (opcode 0xE3, T1)"
# NOP
assert low(real[g.OPCODES["NOP"] * 16 + 1]) == 0x1000
# loads immediate (LDAI anchored at 0x11 by the addressing spec)
assert g.OPCODES["LDAI"] == 0x11, "LDAI must stay 0x11 (doc anchor)"
assert low(real[0x111]) == 0x7009, "LDAI T1"
assert low(real[g.OPCODES["LDBI"] * 16 + 1]) == 0x700A
assert low(real[g.OPCODES["LDCI"] * 16 + 1]) == 0x700B
# memory ops share the T1/T2 MAR-fill prefix
for name in ("LDA", "STA", "JMP", "JNZ"):
    base = g.OPCODES[name] * 16
    assert low(real[base + 1]) == 0x600C, f"{name} T1 (dst=MAR_LO)"
    assert low(real[base + 2]) == 0x600D, f"{name} T2 (dst=MAR_HI)"
assert low(real[g.OPCODES["LDA"] * 16 + 3]) == 0x1011
assert low(real[g.OPCODES["STA"] * 16 + 3]) == 0x101F
assert low(real[g.OPCODES["JMP"] * 16 + 3]) == 0x1080
assert low(real[g.OPCODES["JNZ"] * 16 + 3]) == 0x10C0
# ALU family: END + SA + src=ALU + dst=REG_A. The SA bits in [11:9] are the
# '382 code BIT-REVERSED, because CW9 is labelled SA2 and wired to the chip's
# select MSB — see _sa_bits(). These literals previously held the UNREVERSED
# packing, which is how the encoding stayed wrong: the test agreed with the
# generator and neither agreed with the wiring. ADD and AND swap places here,
# which is exactly the fault the bench measured.
alu_want = {"CLR": 0x1031, "BSUB": 0x1831, "SUB": 0x1431, "ADD": 0x1C31,
            "XOR": 0x1231, "OR": 0x1A31, "AND": 0x1631, "SET": 0x1E31}
for name, w in alu_want.items():
    assert low(real[g.OPCODES[name] * 16 + 1]) == w, f"{name} T1"
# OUT
assert low(real[g.OPCODES["OUT"] * 16 + 1]) == 0x1198
# HALT: bit15 only, NO END bit (rule changed 2026-07-14); rest of block fill
assert low(real[g.OPCODES["HALT"] * 16 + 1]) == 0x8000
assert low(real[g.OPCODES["HALT"] * 16 + 2]) == 0x1000

# ---- diag image: word = own addr[11:0] | ~addr[11:8] in [15:12] ----
diag = g.build_diag()
assert len(diag) == 4096
assert diag[0x000] == 0xF000
assert diag[0xFFF] == 0x0FFF
assert diag[0xA5A] == 0x5A5A
assert diag[0x123] == 0xE123
for a in range(4096):
    assert diag[a] == (a | ((~(a >> 8) & 0xF) << 12))

# ---- builder asserts (design-notes list) fire on crafted bad words ----
#
# Every crafted word gets INERT_THIRD OR'd in. That is not decoration: the
# bank bits are ACTIVE LOW, so a bare 16-bit literal has all three of them
# at 0 and reads as "bank 1 everywhere" -- MISC=MDR_OUT becomes MISC code
# 12, no rule matches, and the negative test silently stops testing
# anything. Exactly the way a checker rots into a no-op.
def must_raise(addr, word, why):
    word |= g.INERT_THIRD
    try:
        g.check_word(addr, word)
    except g.BuildError:
        return
    raise AssertionError(f"check_word accepted {why} ({word:#08x})")

# /MDR_OUT ([8:6]=100) + src!=NONE = two W-bus drivers
must_raise(0x011, 0x1100 | 0x0008, "MDR_OUT plus src=ROM")
# PC_UP together with /PC_LOAD ([8:6]=010)
must_raise(0x011, 0x2080, "PC_UP with PC_LOAD")
# src device == dst device, RAM case
must_raise(0x011, 0x1000 | (0b010 << 3) | 0b111, "src=RAM dst=RAM")
# IR_LOAD (dst=110) outside T0
must_raise(0x011, 0x1006, "IR_LOAD outside T0")
# T0 row that is not the universal fetch
must_raise(0x010, 0x1000, "non-fetch T0 row")
# whole-table check: an opcode block with no END and no HALT runs into fill
bad = list(real)
bad[0x111] = 0x6009 | g.INERT_THIRD   # LDAI T1 with END stripped
try:
    g.check_table(bad)
    raise AssertionError("check_table accepted END-less opcode block")
except g.BuildError:
    pass
g.check_table(real)            # the shipped table must pass its own police

# ---- CLI: bins + header on disk ----
subprocess.run([sys.executable, os.path.join(HERE, "microcode_gen.py")],
               check=True, capture_output=True)
bins = {}
for fn in ("U9.bin", "U15.bin", "U23.bin",
           "U9_diag.bin", "U15_diag.bin", "U23_diag.bin"):
    p = os.path.join(ROMS, fn)
    assert os.path.exists(p), f"missing {fn}"
    bins[fn] = open(p, "rb").read()
    assert len(bins[fn]) == 8192, f"{fn} not AT28C64B-sized (8192B)"
    # A12 is grounded on the board: upper half unreachable, mirror it so a
    # floating/mis-tied A12 still reads the same image
    assert bins[fn][:4096] == bins[fn][4096:], f"{fn} upper half not mirrored"

# byte roles: U9 = word[7:0] (CW0-7), U15 = word[15:8] (CW8-15)
for a in (0x000, 0x111, 0xA5A, 0xFFF):
    assert bins["U9.bin"][a] == real[a] & 0xFF
    assert bins["U15.bin"][a] == (real[a] >> 8) & 0xFF
    assert bins["U23.bin"][a] == third(real[a])
    assert bins["U9_diag.bin"][a] == diag[a] & 0xFF
    assert bins["U15_diag.bin"][a] == diag[a] >> 8
    assert bins["U23_diag.bin"][a] == (~(((a >> 4) & 0xFF) ^ (a & 0x0F))) & 0xFF

# ---- expect header consumed by the rig ----
t = open(HDR).read()
assert t.splitlines()[0].startswith("/* GENERATED by microcode_gen.py"), \
    "missing generated marker"
assert "#include <avr/pgmspace.h>" in t

def hdr_val(name):
    m = re.search(rf"#define {name}\s+0x([0-9A-Fa-f]+)", t)
    assert m, f"header missing {name}"
    return int(m.group(1), 16)

# CRCs are computed over the 4096 ADDRESSABLE bytes (what the rig can walk)
assert hdr_val("MC_CRC_U9_REAL") == g.crc16(bins["U9.bin"][:4096])
assert hdr_val("MC_CRC_U15_REAL") == g.crc16(bins["U15.bin"][:4096])
assert hdr_val("MC_CRC_U9_DIAG") == g.crc16(bins["U9_diag.bin"][:4096])
assert hdr_val("MC_CRC_U15_DIAG") == g.crc16(bins["U15_diag.bin"][:4096])
assert hdr_val("MC_CRC_U23_REAL") == g.crc16(bins["U23.bin"][:4096])
assert hdr_val("MC_CRC_U23_DIAG") == g.crc16(bins["U23_diag.bin"][:4096])
# image-detect signatures
assert hdr_val("MC_REAL_ROW0") == g.FETCH
assert hdr_val("MC_DIAG_ROW0") == 0xF000
# full real-word table in flash, for row-naming diagnostics on the bench
m = re.search(r"MC_REAL_WORDS\[4096\] PROGMEM = \{(.*?)\};", t, re.S)
assert m, "header missing MC_REAL_WORDS[4096]"
words = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{6})UL", m.group(1))]
assert words == real, "MC_REAL_WORDS drifted from build_real()"

# CLI must PRINT the per-chip CRCs (the bench copies them into the log)
out = subprocess.run([sys.executable, os.path.join(HERE, "microcode_gen.py")],
                     check=True, capture_output=True, text=True).stdout
for name in ("MC_CRC_U9_REAL", "MC_CRC_U15_REAL", "MC_CRC_U23_REAL",
             "MC_CRC_U9_DIAG", "MC_CRC_U15_DIAG", "MC_CRC_U23_DIAG"):
    assert f"0x{hdr_val(name):04X}" in out, f"CRC {name} not printed"



def test_IN_reads_the_switches_into_B():
    """IN is the first instruction that makes the machine INTERACTIVE: it puts
    the SW1 byte on W and latches it into B, so an operand comes off the bench
    rather than out of the ROM.

    NETLIST-VERIFIED BEFORE ENCODING (2026-08-02), because a field that agrees
    with its own table and not with the wiring is exactly what the SA bug was:

      input_output.kicad_sch
        SWITCH-GATE1 is a plain buffer, IS0-7 -> W0-7 with NO permutation
        (1A1.2->1Y1.18, 1A2.4->1Y2.16, 1A3.6->1Y3.14, 1A4.8->1Y4.12,
         2A1.11->2Y1.9, 2A2.13->2Y2.7, 2A3.15->2Y3.5, 2A4.17->2Y4.3)
        both halves enabled together: 1~G.1 and 2~G.19 are the SAME net,
        ~{SW_OUT}, so src=SW drives all eight bits or none
        R17-R24 pull IS0-7 to +5V and SW1 pulls them down, so a CLOSED
        switch reads 0 — the byte is ACTIVE LOW at the bench

      alu.kicad_sch
        U46 (TMP_B shadow) D0-7 = W0-7, LE = LE_TMP_B
        U50 is a 74LS02: LE_TMP_B = NOR(~{REG_B_LOAD}, CLK)
        THE SHADOW LATCHES ON ~{REG_B_LOAD}, NOT ON THE LDBI OPCODE, so any
        instruction with dst=REG_B fills TMP_B and ADD will see it.

    IN is therefore one microword and no hardware."""
    assert "IN" in INSTRUCTIONS, "IN is not in the instruction table"
    length, rows = INSTRUCTIONS["IN"]
    assert length == 1, f"IN is one byte, not {length}"
    assert len(rows) == 1, "IN is a single T1 row"
    w = rows[0]
    misc, src, dst = (w >> 6) & 7, (w >> 3) & 7, w & 7
    assert src == SRC["SW"], f"IN must source the switches, not {src}"
    assert dst == DST["REG_B"], f"IN must land in B (TMP_B shadow), not {dst}"
    assert w & (1 << 12), "IN needs END — one T1 row and the block must retire"
    assert not w & (1 << 13), "IN is one byte: no PC_UP beyond the fetch"
    assert not w & (1 << 15), "IN must not set HALT"
    assert misc == 0, f"IN needs no misc strobe, got {misc}"
    real = build_real()
    op = OPCODES["IN"]
    assert real[op * 16 + 1] == w, "IN's T1 row is not in the built table"
    assert low(real[op * 16 + 2]) == 0x1000, "IN's block must safe-fill after T1"
    check_word(op * 16 + 1, w)          # the police must accept it


def test_sa_field_reaches_the_382_uninverted():
    """THE BUG THIS EXISTS FOR: the SA field arrived at the '382s BIT-REVERSED,
    so ADD (011) was executed as AND (110). Three bench images agreed —
    5 AND 3 = 1, 0x39 AND 0 = 0, 0 AND 0x39 = 0 (2026-08-02).

    It survived everything because reversing a field is INVISIBLE unless
    something computes with it. block1 checked ROM -> pin and found them
    self-consistent; alu.ops drove SA from the rig and never used the
    microcode's encoding at all. Nothing compared the ENCODING against the
    WIRING until a program actually ran.

    So this walks the netlist: which CW bit lands on which '382 select pin,
    then asserts the code the chip receives IS the code the mnemonic names.
    """
    import re
    sys.path.insert(0, HERE)
    from kicad_netlist import build_report
    alu = os.path.join(HERE, "..", "..", "dino_v0_0_2", "alu.kicad_sch")

    # netlist: SA0/SA1/SA2 -> U38 pins 5/6/7 = S0/S1/S2
    sel = {}
    for r in build_report(alu)[0]:
        t = str(r)
        m = re.match(r"\s*U38\s+pin\s+(\d+)\s+S(\d)", t)
        if m:
            n = re.search(r"net=(\S+)", t)
            sel[int(m.group(2))] = n.group(1)     # S<n> <- net name
    assert set(sel) == {0, 1, 2}, f"could not find U38 S0/S1/S2: {sel}"

    # The schematic aliases CW9=SA2, CW10=SA1, CW11=SA0.
    #
    # RESOLVE AGAINST THE LABEL SET, NOT THE NET NAME. KiCad names a net after
    # the alphabetically first label on it, so these nets report as
    # `CW11/SA0`, `CW10/SA1`, `CW9/SA2` -- `CW9` beats `SA2` exactly as
    # CLAUDE.md's naming rule says it will. Matching the bare alias made this
    # assertion fire on the GUARD and abort before it compared a single code,
    # and because nothing called this function the module still printed OK and
    # exited 0. Found 2026-08-25; see test_suite_reachability.py.
    cw_of = {"SA0": 11, "SA1": 10, "SA2": 9}
    resolved = {}
    for spin, net in sel.items():
        alias = [p for p in net.split("/") if p in cw_of]
        assert len(alias) == 1, (
            f"U38 S{spin} is on {net!r}, which carries "
            f"{len(alias)} SA aliases -- expected exactly one of {sorted(cw_of)}")
        resolved[spin] = cw_of[alias[0]]

    for name, code in SA.items():
        w = word(sa=name)
        got = 0
        for spin, bit in resolved.items():
            got |= ((w >> bit) & 1) << spin
        assert got == code, (
            f"{name}: microcode encodes {code} but the '382 receives {got} — "
            f"the SA field is reaching the chip permuted")


# ==========================================================================
# The third EEPROM and the stack (2026-08-10)
# ==========================================================================

# ---- 0xFF is today's machine ----
# The load-bearing property of the whole third-ROM design: every new field is
# polarised so an ERASED AT28C64B reproduces the 16-bit machine. If this ever
# stops holding, an unburned U23 stops being harmless and starts asserting
# CIN, a bank switch, or a branch condition on every row.
assert g.INERT_THIRD == 0xFF << 16
assert third(g.FETCH) == 0xFF, "the universal fetch must not touch CW16-23"
assert third(g.FILL) == 0xFF, "safe-fill must not touch CW16-23"

# Every row that predates the stack must still read 0xFF in the third byte.
# Named explicitly rather than derived, so adding an instruction that quietly
# starts using a reserved bit shows up here.
_STACK_OPS = {g.OPCODES[n] for n in
              ("LXISP", "CALL", "RET", "PUSHA", "POPA", "PUSHB", "POPB")}
for a in range(4096):
    if (a >> 4) not in _STACK_OPS:
        assert third(real[a]) == 0xFF, (
            f"row {a:#05x} (opcode {a >> 4:#04x}) uses a third-ROM field, but "
            f"only the stack instructions should")

# ---- bank bits are DERIVED from the code, never passed by hand ----
# word() computes them, so a caller cannot select SP_LO and forget to switch
# banks. Both directions asserted: bank-1 codes clear the bit, bank-0 leave it.
assert third(g.word(src="SP_LO")) & 0x02 == 0, "src=SP_LO must clear ~{SRC_BANK}"
assert third(g.word(src="ROM")) & 0x02 != 0, "src=ROM must leave bank 0 selected"
assert third(g.word(dst="SP_HI")) & 0x04 == 0, "dst=SP_HI must clear ~{DST_BANK}"
assert third(g.word(dst="REG_A")) & 0x04 != 0, "dst=REG_A must leave bank 0"
# and the low three bits are the SAME the old decoder sees -- that is what
# makes widening additive instead of a renumber
assert low(g.word(src="SP_LO")) >> 3 & 7 == 0, "SP_LO is bank-1 code 8 -> CW3-5 = 000"
assert low(g.word(src="PC_LO")) >> 3 & 7 == 2, "PC_LO is bank-1 code 10 -> CW3-5 = 010"

# ---- MISC is full ----
assert g.MISC["SP_UP"] == 0b101 and g.MISC["SP_DOWN"] == 0b111, \
    "SP_UP/SP_DOWN must be U29's O5/O7 -- the last two free MISC codes"
assert set(g.MISC.values()) == set(range(8)) - {0b000} | {0b000}, \
    "MISC now uses all eight codes; O0 is NONE and unreclaimable"

# ---- the stack sequences ----
def rows(name):
    base = g.OPCODES[name] * 16
    return [real[base + t] for t in range(1, 16) if real[base + t] != g.FILL]

# LXISP: two ROM bytes into SP, PC++ on both. Bank-0 SRC into a bank-1 DST,
# which only works because the two bank bits are independent.
lx = rows("LXISP")
assert len(lx) == 2, f"LXISP should be 2 states, got {len(lx)}"
for w, half in zip(lx, ("SP_LO", "SP_HI")):
    m, sr, d = g._fields(w)
    assert sr == g.SRC["ROM"] and d == g.DST[half], f"LXISP {half}"
    assert w & g.PC_UP and w & g.MUX_PC, "LXISP must fetch its operand from ROM"

# PUSH: SP->MAR, store, decrement. Empty-descending.
pu = rows("PUSHA")
assert len(pu) == 4, f"PUSHA should be 4 states, got {len(pu)}"
assert g._fields(pu[0])[1:] == (g.SRC["SP_LO"], g.DST["MAR_LO"])
assert g._fields(pu[1])[1:] == (g.SRC["SP_HI"], g.DST["MAR_HI"])
assert g._fields(pu[2])[1:] == (g.SRC["REG_A"], g.DST["RAM"])
assert g._fields(pu[3])[0] == g.MISC["SP_DOWN"], "PUSH decrements AFTER storing"
assert pu[3] & g.END

# POP: increment FIRST, then load -- the mirror of PUSH's store-then-drop.
po = rows("POPA")
assert len(po) == 4, f"POPA should be 4 states, got {len(po)}"
assert g._fields(po[0])[0] == g.MISC["SP_UP"], "POP increments BEFORE loading"
assert g._fields(po[3])[1:] == (g.SRC["RAM"], g.DST["REG_A"])
assert po[3] & g.END

# PUSH/POP round trip through the same slot: the sequences must be exact
# mirrors or the stack drifts one byte per call.
assert [g._fields(w)[0] for w in pu].count(g.MISC["SP_DOWN"]) == 1
assert [g._fields(w)[0] for w in po].count(g.MISC["SP_UP"]) == 1

# CALL: push return HI, push return LO, THEN fetch the target. The order is
# forced -- MAR is the only 16-bit holder, so the push has to finish before
# the target fetch reuses it.
ca = rows("CALL")
assert len(ca) == 11, f"CALL should be 11 states, got {len(ca)}"
assert g._fields(ca[2])[1:] == (g.SRC["PC_HI"], g.DST["RAM"]), "CALL pushes HI first"
assert g._fields(ca[6])[1:] == (g.SRC["PC_LO"], g.DST["RAM"]), "CALL pushes LO second"
assert g._fields(ca[8])[1:] == (g.SRC["ROM"], g.DST["MAR_LO"]), \
    "CALL fetches the target LAST, once MAR is free"
assert g._fields(ca[10])[0] == g.MISC["PC_LOAD"] and ca[10] & g.END
assert sum(1 for w in [g.FETCH] + ca if w & g.PC_UP) == 3, "CALL is 3 bytes"

# RET: pop two bytes back into MAR, load the PC, then step over CALL's
# operand bytes. C is clobbered because it is the machine's only free
# register and the LO byte has to be parked while MAR is re-pointed.
re_ = rows("RET")
assert g._fields(re_[3])[1:] == (g.SRC["RAM"], g.DST["REG_C"]), \
    "RET parks the return LO byte in C -- the only free register"
# The MDR replay must be the state IMMEDIATELY after the RAM read that
# parked the byte -- MDR holds for exactly one state. RET's second draft put
# the REG_C -> MAR_LO move in between, U18 latched C instead, and the gate
# model loaded the PC with 0x0C0C. check_table polices the ordering now
# (_check_mdr_replay_is_immediate); this pins the shape.
assert g._fields(re_[7])[1] == g.SRC["RAM"], "RET T8 parks the HI byte in MDR"
assert g._fields(re_[8])[0] == g.MISC["MDR_OUT"], \
    "RET T9 must replay IMMEDIATELY -- see _check_mdr_replay_is_immediate"
assert g._fields(re_[8])[2] == g.DST["MAR_HI"]
assert g._fields(re_[9])[1:] == (g.SRC["REG_C"], g.DST["MAR_LO"])
assert g._fields(re_[10])[0] == g.MISC["PC_LOAD"]
assert sum(1 for w in re_[11:] if w & g.PC_UP) == 2, \
    "RET must step over CALL's two operand bytes -- the price of push-first"
assert "RET" in g._PC_UP_EXEMPT, "RET's PC_UP count is intentional; name it"

# ---- the new policing rules fire ----
# bank-1 bus fight: MISC=MDR_OUT alongside a BANK-1 source. This is the one
# collision the hardware cannot prevent, because MISC is an independent field
# while every SRC-driven buffer is one-hot by construction.
try:
    g.check_word(0x011, g.word(misc="MDR_OUT", src="SP_LO"))
    raise AssertionError("check_word accepted MDR_OUT + bank-1 src")
except g.BuildError:
    pass
# SP counted and read in the same word: the '169s commit on the edge that
# ENDS the T-state, so the byte read during it is the PRE-count value.
try:
    g.check_word(0x011, g.word(misc="SP_DOWN", src="SP_LO"))
    raise AssertionError("check_word accepted SP counted and read together")
except g.BuildError:
    pass
# MAR completeness: RAM touched before both halves are loaded
bad = list(real)
base = g.OPCODES["PUSHA"] * 16
bad[base + 2] = g.FILL          # drop the MAR_HI load out of PUSHA
try:
    g.check_table(bad)
    raise AssertionError("check_table accepted RAM access with MAR incomplete")
except g.BuildError:
    pass

# ---- CRC tripwire ----
# These are DELIBERATE constants, not derived: they change only when someone
# means to reburn. All three moved on 2026-08-10 because adding an
# instruction writes rows in EVERY byte of the word -- U9/U15 stay untouched
# only for changes confined to CW16-23.
assert g.crc16(bins["U9.bin"][:4096]) == 0xB5B7, "U9 changed -- reburn intended?"
assert g.crc16(bins["U15.bin"][:4096]) == 0x5174, "U15 changed -- reburn intended?"
assert g.crc16(bins["U23.bin"][:4096]) == 0x2329, "U23 changed -- reburn intended?"

# ---- runner -------------------------------------------------------------
# ENUMERATED, not a hand-written list. A tuple of names is a step someone has
# to remember, and forgetting it is exactly how this module's two test_
# functions went unrun from the day they were written. Guarded by
# test_suite_reachability.py.
if __name__ == "__main__":
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"  ok   {_name}")
        except AssertionError as _e:
            _failed.append((_name, _e))
            print(f"  FAIL {_name}: {_e}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_microcode_gen")
