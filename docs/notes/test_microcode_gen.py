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
# 0xF5 is unassigned and stays that way: 0xFx holds only HALT. Phase F+
# filled 0xE3, which this line used to name.
assert low(real[0xF51]) == 0x1000, "safe-fill missing (opcode 0xF5, T1)"
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

# Every OTHER row must still read 0xFF in the third byte. Named explicitly
# rather than derived, so an instruction that quietly starts using a reserved
# bit shows up HERE rather than on the bench. Each group names WHICH field it
# spends and why -- a bare list of opcodes would not survive the next phase.
# THE RULE, NOT A NAME LIST. At 66 instructions the allowed set could be
# enumerated by hand; at 174 a hand list rots on the next addition and stops
# being read. So: an opcode may touch CW16-23 if and only if one of its rows
# names a BANK-1 src/dst code or carries a `cond`. Anything else touching the
# third ROM means a reserved bit got spent by accident.
#
# The COUNT is the tripwire. The rule alone would accept a new instruction
# silently; the count makes every addition that spends a third-ROM bit a
# deliberate edit here.
def _may_touch_third(rows):
    for w in rows:
        if not (w & g.SRC_BANK_N) or not (w & g.DST_BANK_N):
            return True                      # bank 1 selected
        if not (w & g.MISC_BANK_N):
            return True
        if ((w >> 6) & 7) == g.MISC["COND"]:
            return True                      # FLAG_SEL0/1 + FLAG_POL
    return False


_THIRD_ROM_OPS = {g.OPCODES[n] for n, (_, rows) in g.INSTRUCTIONS.items()
                  if _may_touch_third(rows)}
assert len(_THIRD_ROM_OPS) == 68, (
    f"the third-ROM group is {len(_THIRD_ROM_OPS)}, not 68 -- an instruction "
    f"started or stopped spending a CW16-23 bit. Deliberate?")
_actually = {a >> 4 for a in range(4096) if third(real[a]) != 0xFF}
assert _actually == _THIRD_ROM_OPS, (
    f"rows touch the third ROM that the rule does not allow: "
    f"{sorted(hex(o) for o in _actually - _THIRD_ROM_OPS)}")
for a in range(4096):
    if (a >> 4) not in _THIRD_ROM_OPS:
        assert third(real[a]) == 0xFF, (
            f"row {a:#05x} (opcode {a >> 4:#04x}) uses a third-ROM field but "
            f"names no bank-1 code and no cond")

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
# PHASE F, 2026-08-27. All three moved and all three were EXPECTED to move:
# forty-one new opcodes write rows in every byte of the word, IN's row left,
# and JNZ gained cond=("Z",1) which clears CW22. U23 would have moved on the
# JNZ cure alone.
#
#   before phase F   U9 0xB5B7   U15 0x5174   U23 0x2329
#   phase F (66)     U9 0xB111   U15 0xFE5E   U23 0xD8F4   never burned
#   phase F+ (174)   below. The 66-instruction set was superseded before it
#                    reached a programmer, so 0xB111/0xFE5E/0xD8F4 name a ROM
#                    that never existed in silicon. Say so rather than
#                    leaving three orphan CRCs in the log.
#   phase F+ (174)   U9 0x99A0   U15 0xBFEF   U23 0xCB8E   MVI was BROKEN
#   MVI fixed        below. U23 DID NOT MOVE: the fix is confined to CW0-15,
#                    so only U9 and U15 need reburning.
#   MVI fixed        U9 0xC64E   U15 0x61BF   U23 0xCB8E
#   settling states  below. U23 UNCHANGED again: the pad rows spend no
#                    third-ROM field, so only U9 and U15 need reburning.
#   settling states  U9 0xE991   U15 0x33EA   U23 0xCB8E   BURNED 2026-09-01
#   MVI settle       below. U23 UNCHANGED a third time: the MVI family's rows
#                    spend no third-ROM field and neither does the settle, so
#                    U9 and U15 only. Found on silicon 2026-09-05 by
#                    PROG_test5: the park closed on the RAM's old byte.
#   MVI settle       U9 0xC52B   U15 0xAE3F   U23 0xCB8E   BURNED 2026-09-05,
#                    WRONG: pc_up on the park row, U18 latched the next byte
#   MVI settle v2    below. pc_up moved to the settle row: bit 13, U15 only.
assert g.crc16(bins["U9.bin"][:4096]) == 0xC52B, "U9 changed -- reburn intended?"
assert g.crc16(bins["U15.bin"][:4096]) == 0xDCD1, "U15 changed -- reburn intended?"
assert g.crc16(bins["U23.bin"][:4096]) == 0xCB8E, "U23 changed -- reburn intended?"


def test_no_row_asks_the_address_bus_for_two_things():
    """THE DEFECT THIS EXISTS FOR, found on the bench 2026-08-27.

    There is one address bus. CW14 points M at the PC or at MAR. A ROM fetch
    needs the PC; a RAM access needs MAR. MVI/MVIX/MVIS were encoded as
    src=ROM dst=RAM in a single state, which asks for both -- so the mux
    stayed on the PC and the immediate was written to a ROM address, where
    it evaporated.

    IT DID NOT FAIL LOUDLY. It failed as a program whose answer CHANGED ON
    EVERY RESET, because the loop counter MVI was supposed to initialise came
    from uninitialised RAM instead. Nothing in check_word looked at CW14 at
    all, so 174 instructions passed the police with three of them unable to
    work, and the oracle agreed with them because it wrote to `mar` without
    consulting the mux either."""
    real = build_real()
    for a, w in enumerate(real):
        misc, src, dst = g._fields(w)
        mux = bool(w & g.MUX_PC)
        assert not (src == SRC["ROM"] and dst == DST["RAM"]), \
            f"row {a:#05x}: src=ROM with dst=RAM"
        assert not (mux and (src == SRC["RAM"] or dst == DST["RAM"])), \
            f"row {a:#05x}: RAM accessed with the mux on the PC"
        assert not (src == SRC["ROM"] and not mux), \
            f"row {a:#05x}: src=ROM with the mux on MAR"
    for bad, why in (
            (g.word(end=True, src="ROM", dst="RAM", mux_pc=True, pc_up=True),
             "src=ROM dst=RAM"),
            (g.word(end=True, src="RAM", dst="REG_A", mux_pc=True),
             "src=RAM with mux_pc"),
            (g.word(end=True, src="REG_A", dst="RAM", mux_pc=True),
             "dst=RAM with mux_pc")):
        try:
            check_word(0x111, bad)
            raise AssertionError(f"check_word accepted {why}")
        except g.BuildError:
            pass


def test_MVI_parks_the_byte_in_MDR_and_replays_it():
    """The cure, and it costs TWO T-states, not one. Fetch with the mux on
    the PC and NO destination -- which parks the byte in MDR for free -- then
    SETTLE with the mux still on the PC and no source, then replay it with
    the mux on MAR.

    Why the settle, 2026-09-05, on silicon: CW14 comes straight off the ROM
    and flips M from the PC to MAR ~30ns before the source decode retires
    ~{ROM_OUT}. In that window M15 is high and ~{ROM_OUT} is still low, so
    FETCH_RAM = NOR(~{ROM_OUT}, ~{RAM_EN}) fires, the RAM drives the cell's
    OLD byte onto MDR, and U18 is still transparent because LE_MDR closes on
    READS_IDLE, three gates after the decode. The park shuts on a fight.
    PROG_test5 slots 2/3: MVI 0x9E, read back 0x90 and 0x9F; MVI 0x02, read
    0x03. PROG_isa never saw it: PLANT rewrites the same 0x2E every subtest.
    The monitor was the first image to MVI a cell holding a different value.

    With a src=NONE row between, READ drops while M is still in ROM: nothing
    can turn on, the latch closes on a bus U19 released and that holds its
    charge, and only then does M flip.

    And the PC steps in the SETTLE, not in the park. The first settle cut
    (burned 2026-09-05, U9 0xC52B / U15 0xAE3F) stepped the PC in the park
    row; the ROM's address moved at the boundary and ~150ns later U19 was
    carrying the NEXT byte into a still-open U18. test5 read 0x00/0xFF."""
    for name, nbytes in (("MVI", 4), ("MVIX", 2), ("MVIS", 2)):
        length, rows = INSTRUCTIONS[name]
        assert length == nbytes, f"{name} is {length} bytes, want {nbytes}"
        park, settle, replay = rows[-3], rows[-2], rows[-1]
        assert (park >> 3) & 7 == SRC["ROM"] and park & 7 == DST["NONE"], \
            f"{name}: the park row must fetch with no destination"
        assert park & g.MUX_PC, f"{name}: the fetch needs the mux on the PC"
        assert (settle >> 3) & 7 == SRC["NONE"] and settle & 7 == DST["NONE"] \
            and (settle >> 6) & 7 == g.MISC["NONE"], \
            f"{name}: the settle row must drive and load nothing"
        assert settle & g.MUX_PC and settle & g.PC_UP, \
            f"{name}: the settle keeps M on the PC and is where the PC steps"
        assert not park & g.PC_UP, \
            f"{name}: the park must NOT step the PC -- the ROM's address has " \
            f"to stay put until U18 shuts (first settle cut read the next byte)"
        assert (replay >> 6) & 7 == g.MISC["MDR_OUT"], \
            f"{name}: the row after the settle must replay out of MDR"
        assert replay & 7 == DST["RAM"], f"{name}: the replay writes RAM"
        assert not replay & g.MUX_PC, \
            f"{name}: the write needs the mux back on MAR"


def test_no_rom_park_flips_M_before_the_latch_closes():
    """The hazard behind test_MVI..., stated for EVERY opcode: a row that
    parks a ROM byte (src=ROM, dst=NONE, mux on PC) must not be followed by
    a row with the mux on MAR. FETCH_RAM fires on that flip while the read is
    still retiring and U18 is still open. A RAM-side park is exempt: M stays
    on MAR through the replay and nothing else can join the bus."""
    bad = []
    for name, (_, rows) in INSTRUCTIONS.items():
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if ((a >> 3) & 7 == SRC["ROM"] and a & 7 == DST["NONE"]
                    and a & g.MUX_PC and not b & g.MUX_PC):
                bad.append(f"{name} T{i + 2}")
    assert not bad, f"ROM park followed by an M flip: {bad}"


# ---- PHASE F, step 2: the free set ---------------------------------------
# Every test below was written BEFORE the rows existed (RED first, working
# rule 2). They encode SECTION 2's table and SECTION 6's opcode map from
# `.git/sdd/PHASE_F.md`, which are themselves netlist-derived.


def test_IN_is_retired_from_the_isa():
    """IN IS GONE, and it left in three stages, each a different KIND of gone.

    PHASE E, 2026-08-25 -- retired in COPPER. `U28.7` unlanded, `~{SW_OUT}`
    deleted, SW1 answers at an ADDRESS instead (card zero, 0x4000-0x47FF) and
    `LDA` replaces it. The microcode row survived that step because phase E
    burned no microcode ROM and deleting a row would have cost a three-ROM
    burn for nothing.

    PHASE F, 2026-08-27 (Rico) -- retired in the ISA. This burn writes all
    three ROMs anyway, so the row now costs nothing to remove and 0x52 comes
    back. Executing `IN` on today's copper reads an UNDEFINED byte, not the
    park: `src=SW` asserts `SRC_ACTIVE` so `U25` is enabled, but SW asserts
    neither `~{ROM_OUT}` nor `~{RAM_OUT}`, so `READS_IDLE` stays high and
    `U25` drives W from a floating MDR. A decodable opcode that reads garbage
    is worse than no opcode at all.

    So this is the test that stops it coming back."""
    assert "IN" not in INSTRUCTIONS, "IN's microcode row survived the phase-F burn"
    assert "IN" not in OPCODES, "IN still owns an opcode"
    # 0x52 IS REUSED, as OUTB, and that is safe ONLY because the same burn
    # frees it and reassigns it. No ROM ever exists in which 0x52 means IN
    # while something else decodes it. Reusing a freed opcode ACROSS burns is
    # the hazard; within one burn there is no window.
    assert OPCODES["OUTB"] == 0x52, "0x52 was freed by IN and taken by OUTB"
    assert not any(g.SRC["SW"] == ((w >> 3) & 7) and not (w & g.SRC_BANK_N) == 0
                   for _, rows in INSTRUCTIONS.values() for w in rows), \
        "some row still sources SW"


# SECTION 6's map, retyped ONCE here so the encoder and the document cannot
# drift apart silently. A collision is a BuildError below, not a comment.
_PHASE_F_OPCODES = {
    "RST": 0x01,
    "LDB": 0x23, "LDC": 0x24, "STB": 0x25, "STC": 0x26,
    "LDAS": 0x27, "STAS": 0x28,
    "JMPX": 0x35, "JMPSP": 0x36, "JNC": 0x37,
    "CMP": 0x49, "CMPB": 0x4A, "TST": 0x4B,
    "SHL": 0x4C, "INR": 0x4D, "DCR": 0x4E, "NOT": 0x4F,
    "PUSHC": 0x65, "POPC": 0x66,
    "INXSP": 0x67, "DCXSP": 0x68, "SPHL": 0x69, "HLSP": 0x6A,
    "LDAX": 0x71, "STAX": 0x72, "LDBX": 0x73, "STBX": 0x74,
    "LDCX": 0x75, "STCX": 0x76,
    "MOVAB": 0x81, "MOVAC": 0x82, "MOVBA": 0x83,
    "MOVBC": 0x84, "MOVCA": 0x85, "MOVCB": 0x86,
    "MOVASPL": 0x87, "MOVASPH": 0x88, "MOVSPLA": 0x89, "MOVSPHA": 0x8A,
    "MOVAPCL": 0x8B, "MOVAPCH": 0x8C,
}


def test_phase_f_opcode_map_matches_the_spec():
    """41 new opcodes, none colliding with the 25 that survive."""
    for name, op in _PHASE_F_OPCODES.items():
        assert name in OPCODES, f"{name} has no opcode"
        assert OPCODES[name] == op, \
            f"{name} is {OPCODES[name]:#04x}, SECTION 6 says {op:#04x}"
        assert name in INSTRUCTIONS, f"{name} has an opcode but no rows"
    assert len(set(OPCODES.values())) == len(OPCODES), \
        "two mnemonics share an opcode"
    assert len(_PHASE_F_OPCODES) == 41, "SECTION 2 counts 40 free + JNC"


def test_0x00_stays_NOP():
    """RULED BY RICO 2026-08-27, at the burn, exactly as SECTION 8 scheduled.

    The OPEN was: blank RAM is 0x00 and 0x00 is NOP, so since phase D a PC
    that lands in unwritten RAM NOP-slides through 28KB and wraps silently --
    a failed STORE presenting as a failed FETCH. The ruling is KEEP: 0x00 =
    NOP is what every other 8-bit machine does, a NOP slide is a legitimate
    idiom, and HALT at 0x00 would make a mistyped immediate stop the machine
    instead of stepping over it. Recorded here so the question is CLOSED and
    not re-opened by the next reader of PHASE_F SECTION 8."""
    assert OPCODES["NOP"] == 0x00
    assert OPCODES["HALT"] == 0xFF


def test_cond_refuses_a_flag_the_mux_cannot_select():
    """THE TRAP THIS EXISTS FOR, and it is invisible unless something computes.

    `U77` is a 2:1 on `CW21` alone. `CW22` is a NO-CONNECT. `FLAG_SEL` is
    {C:0b00, Z:0b01, V:0b10, N:0b11}, so `V` and `N` both have bit 0 CLEAR --
    encoding either would drive `CW21` LOW and hand `U62.3` `FLAG_C`. It
    would assemble, pass check_word, burn, and branch on the wrong flag with
    nothing to say so. Refuse it at the encoder until `CW22` is landed."""
    for flag in ("V", "N"):
        try:
            word(end=True, misc="COND", cond=(flag, 1))
            raise AssertionError(f"cond={flag} encoded with CW22 unlanded")
        except g.BuildError:
            pass
    for flag in ("C", "Z"):
        word(end=True, misc="COND", cond=(flag, 1))    # must NOT raise


def test_cond_refuses_pol_zero():
    """`word()` documents `taken = flag XOR pol`. The BUILT hardware is
    `COND_TAKEN = NOR(~{COND}, flag)` -- i.e. `flag XOR 1` -- because there
    is no '86 in this machine at all. Encoder and copper agree only at
    `pol=1`, and `pol=0` encodes cleanly today, clears CW23, and would invert
    every branch the day polarity lands."""
    try:
        word(end=True, misc="COND", cond=("Z", 0))
        raise AssertionError("cond with pol=0 encoded")
    except g.BuildError:
        pass


def test_jnz_now_names_its_flag_and_clears_cw22():
    """THE CURE, and it must ride this burn.

    Today's JNZ is a bare `misc="COND"`, which leaves the third ROM's default
    word: CW21=1, CW22=1, CW23=1. Under FLAG_SEL, {CW22,CW21} = 0b11 is `N`,
    not `Z`. It behaves as Z only because FLAG_Z was hardwired to U62.3.
    Land a 4:1 on {CW22,CW21} later without a reburn and every JNZ in the
    machine becomes JNN. Writing it as cond=("Z",1) drives CW22 to 0 now, so
    the second mux stage is itself inert when it lands."""
    w = INSTRUCTIONS["JNZ"][1][-1]
    assert (w >> 21) & 1, "JNZ must leave CW21 HIGH -- U77 selects I1 = FLAG_Z"
    assert not (w >> 22) & 1, "JNZ still carries CW22=1: it would become JNN"
    assert (w >> 23) & 1, "JNZ must leave CW23 (FLAG_POL) HIGH"
    assert (w >> 6) & 7 == g.MISC["COND"]


def test_jnc_is_jnz_but_for_cw21():
    """JNC is the ONLY instruction in the whole free set that needs the '157,
    and it differs from JNZ in exactly one bit."""
    jnz, jnc = INSTRUCTIONS["JNZ"], INSTRUCTIONS["JNC"]
    assert jnz[0] == jnc[0] == 3, "both are three bytes"
    assert len(jnz[1]) == len(jnc[1]) == 3
    assert jnz[1][:2] == jnc[1][:2], "both open with _MARFILL"
    a, b = jnz[1][-1], jnc[1][-1]
    assert a ^ b == (1 << 21), \
        f"JNZ and JNC differ in {a ^ b:#08x}, must be CW21 alone"
    assert not (b >> 21) & 1, "JNC must drive CW21 LOW to select I0 = FLAG_C"


def test_cw21_is_high_on_every_row_that_is_not_a_branch():
    """The INERT PROOF, still true after the burn.

    `U77`'s select is CW21 and `I1` is FLAG_Z, so every non-branch row must
    leave CW21 high or the mux would hand U62.3 the carry during rows that
    have no business touching the condition path. Only JNC may drive it low."""
    low = sorted((name, t) for name, (_, rows) in INSTRUCTIONS.items()
                 for t, w in enumerate(rows, 1) if not (w >> 21) & 1)
    assert low == [("JCM", 9), ("JCX", 3), ("JNC", 3)], \
        f"CW21 driven low outside the carry branches: {low}"
    assert (g.FILL >> 21) & 1, "SAFE_FILL must leave CW21 high"
    assert (g.FETCH >> 21) & 1, "FETCH must leave CW21 high"


def test_mov_a_c_retires_the_ldci_gap():
    """LDCI and NOP are CLAUDE.md's two never-executed instructions, and LDCI
    is unreachable BY DESIGN: C is RET's return-address scratch and nothing
    can read it back. That is a MICROCODE-SOFT gap and this is the one row
    that closes it."""
    length, rows = INSTRUCTIONS["MOVAC"]
    assert length == 1 and len(rows) == 1, "MOV A,C is one byte, one row"
    w = rows[0]
    assert (w >> 3) & 7 == SRC["REG_C"], "MOV A,C must source C"
    assert w & 7 == DST["REG_A"], "MOV A,C must land in A"
    assert w & (1 << 12), "MOV A,C needs END"
    assert not w & (1 << 13), "one byte: no PC_UP beyond the fetch"
    check_word(OPCODES["MOVAC"] * 16 + 1, w)


def test_no_instruction_reads_the_ALU_the_state_after_loading_it():
    """THE TIMING FAULT THIS EXISTS FOR, 2026-08-27.

    An instruction that loads an ALU operand and reads the ALU in the VERY
    NEXT state gives the '382 pair no settling time. At 500kHz all 147
    subtests of PROG_isa pass; at 1.024MHz the same image returns varying
    subtest numbers from identical resets. Subtract loses margin first --
    a '382 complements B before the adder starts, and ADI passed in the same
    run that SUI failed.

    Every such instruction now carries a SETTLE state. This is the check
    that a new one cannot be added without it."""
    bad = []
    for name, (_, rows) in INSTRUCTIONS.items():
        for i in range(len(rows) - 1):
            _, _, d0 = g._fields(rows[i])
            _, s1, _ = g._fields(rows[i + 1])
            if d0 in (DST["REG_A"], DST["REG_B"]) and s1 == SRC["ALU"]:
                bad.append(f"{name} T{i+1}->T{i+2}")
    assert bad == [], \
        f"these load an ALU operand and read the ALU in the next state, " \
        f"with no settling row: {bad}"


def test_the_tmp_shadow_instructions_are_two_rows():
    """SHL/INR/DCR/NOT lean on the shadow:
    `LE_TMP_B = NOR(~{REG_B_LOAD}, CLK)` follows the LOAD STROBE, not the
    opcode, so any row with dst=REG_B fills TMP_B and the NEXT row's ALU op
    sees it. All four CLOBBER B, which is the price and is not hidden."""
    want = {"SHL": ("ADD", SRC["REG_A"]), "INR": ("SUB", SRC["ALU"]),
            "DCR": ("ADD", SRC["ALU"]), "NOT": ("XOR", SRC["ALU"])}
    for name, (sa_name, first_src) in want.items():
        length, rows = INSTRUCTIONS[name]
        assert length == 1, f"{name} is one byte"
        assert len(rows) == 3, f"{name} is three rows, got {len(rows)}"
        assert (rows[0] >> 3) & 7 == first_src, f"{name} row 1 source"
        assert rows[0] & 7 == DST["REG_B"], f"{name} row 1 must fill TMP_B"
        assert rows[1] == g.SETTLE, (
            f"{name} row 2 must be the SETTLING state -- the '382 pair "
            f"needs a state between the operand latch closing and the "
            f"ALU being read")
        assert (rows[2] >> 3) & 7 == SRC["ALU"], f"{name} row 3 is the ALU op"
        assert rows[2] & 7 == DST["REG_A"], f"{name} row 3 lands in A"
        assert g.SA[sa_name] == g._sa_bits((rows[2] >> 9) & 7), \
            f"{name} row 3 must be sa={sa_name}"
        assert rows[2] & (1 << 12), f"{name} must END"


def test_the_compares_write_no_destination():
    """CMP/CMPB/TST exist because `U49` has NO CLOCK ENABLE -- it re-clocks
    every T-state and `U48`'s select is `~{ALU_OUT}`, so an ALU row sets the
    flags whether or not anything latches the result. DST 0 is `U30.O0`, the
    NONE slot, a no-connect by design."""
    for name, sa_name in (("CMP", "SUB"), ("CMPB", "BSUB"), ("TST", "OR")):
        length, rows = INSTRUCTIONS[name]
        assert length == 1 and len(rows) == 1, f"{name} is one byte, one row"
        w = rows[0]
        assert (w >> 3) & 7 == SRC["ALU"], f"{name} sources the ALU"
        assert w & 7 == DST["NONE"], f"{name} must have NO destination"
        assert g.SA[sa_name] == g._sa_bits((w >> 9) & 7), f"{name} sa"
        assert w & (1 << 12), f"{name} must END"


def test_the_pointer_instructions_load_both_mar_halves_first():
    """`_check_mar_before_ram` polices this globally; this names the shape.
    B:C is the index pair -- C is the LOW byte because MAR_LO is loaded
    first, and a swapped pair is an off-by-256 that a same-pointer round
    trip cannot see (the PROG_sp1 lesson)."""
    for name in ("LDAX", "LDBX", "LDCX", "STAX", "STBX", "STCX"):
        length, rows = INSTRUCTIONS[name]
        assert length == 1, f"{name} is one byte -- the pointer is in B:C"
        assert len(rows) == 3, f"{name} is three rows"
        assert (rows[0] >> 3) & 7 == SRC["REG_C"] and rows[0] & 7 == DST["MAR_LO"]
        assert (rows[1] >> 3) & 7 == SRC["REG_B"] and rows[1] & 7 == DST["MAR_HI"]
    for name in ("LDAS", "STAS", "JMPSP"):
        rows = INSTRUCTIONS[name][1]
        assert rows[:2] == g._SP_TO_MAR, f"{name} must open with the SP->MAR prefix"


def test_every_new_row_survives_the_police():
    """check_word + check_table over the built image is the real gate; this
    fails NAMING THE INSTRUCTION rather than the row address, because a bare
    row number in a 4096-entry table is a blind counter."""
    for name, (_, rows) in INSTRUCTIONS.items():
        base = OPCODES[name] * 16
        for t, w in enumerate(rows, 1):
            try:
                check_word(base + t, w)
            except g.BuildError as e:
                raise AssertionError(f"{name} T{t}: {e}")
    build_real()


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
