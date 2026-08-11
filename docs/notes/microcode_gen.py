#!/usr/bin/env python3
"""DINO microcode ROM image generator.

Symbolic instruction table (dino_session_state.md "Instruction microwords")
-> U9.bin (word[7:0] = CW0-7) + U15.bin (word[15:8] = CW8-15), the diag
image pair, printed per-chip CRC16s, and the rig's expect header
(tests/dino_bringup/src/microcode_expect.h) so rig and ROM can never
disagree.

Address = {IR[7:0], T[3:0]} = opcode*16 + T. 4096 rows; A12 is grounded on
the board, so each 8K AT28C64B carries the image twice (mirrored halves).

Hard rules (session state, decision item 3 + HALT rule change 2026-07-14):
  - ALL 4096 rows programmed; unused rows = SAFE-FILL 0x1000 (END).
  - T0 of ALL 256 opcodes = universal fetch 0x600E.
  - HALT word = 0x8000, bit15 only, NO END bit.

Diag image (test spec "ROM images"): word = own 12-bit address in [11:0],
INVERTED top address nibble in [15:12] — catches stuck-high data lines.

Builder asserts implement the list in dino_design_notes.md ("Builder
assert list") — the POLICY layer of the four-layer defense.

Run: python3 microcode_gen.py            (writes roms/ + expect header)
Test: python3 test_microcode_gen.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROMS = os.path.normpath(os.path.join(HERE, "..", "..", "roms"))
HDR = os.path.normpath(os.path.join(
    HERE, "..", "..", "tests", "dino_bringup", "src", "microcode_expect.h"))

# ---- control word bit map (session state, v0.0.3, COMPLETE) ------------
HALT_BIT = 1 << 15          # raw tap, active high
MUX_PC = 1 << 14            # PC_MAR_MUX: PC=1, MAR=0
PC_UP = 1 << 13             # raw tap
END = 1 << 12               # raw tap

SA = {"CLR": 0b000, "BSUB": 0b001, "SUB": 0b010, "ADD": 0b011,
      "XOR": 0b100, "OR": 0b101, "AND": 0b110, "SET": 0b111}  # [11:9]

# U29's O5 and O7 were the last two free MISC codes; the stack spends both.
# O0 is the NONE slot and can never be reclaimed, so MISC IS NOW FULL -- the
# next code needs ~{MISC_BANK} wired plus a second '138, or step 1's I/O
# decode retiring REG_OUT_LOAD to free O6.
MISC = {"NONE": 0b000, "PC_CLEAR": 0b001, "PC_LOAD": 0b010, "COND": 0b011,
        "MDR_OUT": 0b100, "SP_UP": 0b101, "REG_OUT_LOAD": 0b110,
        "SP_DOWN": 0b111}                                     # [8:6] U29

# SRC/DST codes 0-7 are BANK 0 (U28/U30, unchanged since the ROMs were first
# burned). Codes 8-15 are BANK 1 (U70/U71), reached by driving the matching
# bank bit LOW. The low three bits are the SAME CW3-CW5 / CW0-CW2 the old
# decoder sees; only the enable moves. That is what makes widening additive:
# every burned row stays valid and nothing re-encodes.
SRC = {"NONE": 0b000, "ROM": 0b001, "RAM": 0b010, "REG_A": 0b011,
       "REG_B": 0b100, "REG_C": 0b101, "ALU": 0b110, "SW": 0b111,  # [5:3] U28
       # bank 1 (U70). Code 8 MUST be a real source, never a NONE slot:
       # SRC_ACTIVE is U28.O0 and floats HIGH whenever U28 is disabled, so
       # every bank-1 code already reads "a source is active" -- which is
       # what turns the U25 bridge on so the byte reaches W. A bank-1 NONE
       # would let MDR quietly supply W with nothing driving it.
       "SP_LO": 8, "SP_HI": 9, "PC_LO": 10, "PC_HI": 11}

DST = {"NONE": 0b000, "REG_A": 0b001, "REG_B": 0b010, "REG_C": 0b011,
       "MAR_LO": 0b100, "MAR_HI": 0b101, "IR": 0b110, "RAM": 0b111,  # [2:0] U30
       # bank 1 (U71). These drive the '169s' ~PE, a SYNCHRONOUS load enable
       # -- which is why the stack needs no SP_LOAD misc code and why MISC
       # got away with the two slots it had left.
       "SP_LO": 8, "SP_HI": 9}

# ---- the third EEPROM, CW16-23 (U23) -----------------------------------
# Every bit is ACTIVE LOW so that 0xFF -- an erased AT28C64B -- is today's
# machine. Same reasoning that made HALT=0xFF: the safe state has to be the
# blank state, or an unburned ROM rants instead of idling.
CIN_SEL_N = 1 << 16     # 0 = ALU_CIN follows FLAG_C (ADC/SBB); 1 = opcode path
SRC_BANK_N = 1 << 17    # 0 = SRC bank 1 (U70); 1 = bank 0 (U28)
DST_BANK_N = 1 << 18    # 0 = DST bank 1 (U71); 1 = bank 0 (U30)
MISC_BANK_N = 1 << 19   # 0 = MISC bank 1; 1 = bank 0.  UNWIRED, in reserve
ADDR_SEL1_N = 1 << 20   # with CW14 as ADDR_SEL0.       UNWIRED, in reserve
FLAG_SEL0 = 1 << 21     # '153 4:1 select, bit 0  \  UNWIRED, in reserve
FLAG_SEL1 = 1 << 22     # '153 4:1 select, bit 1   >  sel 00=C 01=Z 10=V 11=N
FLAG_POL = 1 << 23      # '86 polarity           /   taken = flag XOR pol

# Every third-ROM bit set = the inert word. word() starts here and CLEARS
# bits, so a field nobody names is automatically safe.
INERT_THIRD = 0xFF << 16

FLAG_SEL = {"C": 0b00, "Z": 0b01, "V": 0b10, "N": 0b11}


def _sa_bits(code):
    """Pack a '382 function code into CW9..CW11 BIT-REVERSED.

    The schematic labels CW9=SA2, CW10=SA1, CW11=SA0, and wires SA0 -> S0,
    SA1 -> S1, SA2 -> S2. So CW9 carries the '382's select MSB and CW11 its
    LSB. Packing the code LSB-first at CW9 therefore delivers it REVERSED:
    ADD (011) arrived as 110 = AND, which is precisely what the bench measured
    — 5 AND 3 = 1, 0x39 AND 0 = 0, 0 AND 0x39 = 0, three independent images
    all matching (2026-08-02).

    This survived every earlier test because reversing a field is INVISIBLE
    unless something computes with it: block1 checked ROM -> pin and found them
    self-consistent, and alu.ops drove SA from the rig, never using the
    microcode's encoding at all. test_microcode_gen.py now cross-checks this
    against the NETLIST so it cannot come back.
    """
    return ((code & 1) << 2) | (code & 2) | ((code >> 2) & 1)


def word(mux_pc=False, pc_up=False, end=False, halt=False,
         sa=None, misc="NONE", src="NONE", dst="NONE",
         cin_from_flag_c=False, cond=None):
    """One 24-bit control word.

    `src`/`dst` name a code in EITHER bank -- the bank bit is derived from
    the code, never passed by hand, so a caller cannot select `SP_LO` and
    forget to switch banks.

    `cond=(flag, pol)` encodes the '153/'86 branch glue: `flag` is one of
    C/Z/V/N and `pol` is 0 or 1, with `taken = flag XOR pol`. The hardware
    does not exist yet; the field is burned now so it never needs a reburn.
    """
    w = INERT_THIRD
    if halt: w |= HALT_BIT
    if mux_pc: w |= MUX_PC
    if pc_up: w |= PC_UP
    if end: w |= END
    if sa is not None: w |= _sa_bits(SA[sa]) << 9

    m, s, d = MISC[misc], SRC[src], DST[dst]
    w |= (m & 7) << 6
    w |= (s & 7) << 3
    w |= (d & 7)
    # Codes 8-15 live in bank 1, selected by driving the bank bit LOW.
    if s >= 8: w &= ~SRC_BANK_N
    if d >= 8: w &= ~DST_BANK_N
    if m >= 8: w &= ~MISC_BANK_N

    if cin_from_flag_c: w &= ~CIN_SEL_N
    if cond is not None:
        flag, pol = cond
        sel = FLAG_SEL[flag]
        if not (sel & 1): w &= ~FLAG_SEL0
        if not (sel & 2): w &= ~FLAG_SEL1
        if not pol: w &= ~FLAG_POL
    return w


FETCH = word(mux_pc=True, pc_up=True, src="ROM", dst="IR")   # 0x600E
FILL = word(end=True)                                        # 0x1000, END

# ---- opcode assignments -------------------------------------------------
# PROPOSED TABLE (2026-07-16). Only LDAI=0x11 is documented (addressing
# example in dino_session_state.md) — everything else is a fresh assignment:
# high nibble = family (0=ctl, 1=imm loads, 2=memory, 3=flow, 4=ALU, 5=io),
# HALT=0xFF so an ERASED program EEPROM (all 0xFF) halts instead of raving.
# Renumbering = edit here, rerun, reburn; the rig follows via the header.
OPCODES = {
    "NOP": 0x00,
    "LDAI": 0x11, "LDBI": 0x12, "LDCI": 0x13,
    "LDA": 0x21, "STA": 0x22,
    "JMP": 0x31, "JNZ": 0x32,
    "ADD": 0x41, "SUB": 0x42, "AND": 0x43, "OR": 0x44,
    "XOR": 0x45, "CLR": 0x46, "SET": 0x47, "BSUB": 0x48,
    "OUT": 0x51, "IN": 0x52,        # the I/O group
    # --- the stack, 2026-08-10 ------------------------------------------
    # LXISP joins the immediate-load family; CALL/RET join flow; PUSH/POP
    # open a 0x6x stack family. All five are reachable only because the
    # third EEPROM widened SRC and DST.
    "LXISP": 0x14,
    "CALL": 0x33, "RET": 0x34,
    "PUSHA": 0x61, "POPA": 0x62, "PUSHB": 0x63, "POPB": 0x64,
    "HALT": 0xFF,
}

# operand-fetch prefix shared by every MAR-consuming instruction:
# T1 -> MAR_LO, T2 -> MAR_HI (both fetch a byte, PC++)
_MARFILL = [word(mux_pc=True, pc_up=True, src="ROM", dst="MAR_LO"),   # 0x600C
            word(mux_pc=True, pc_up=True, src="ROM", dst="MAR_HI")]   # 0x600D


def _alu(op):
    return [word(end=True, sa=op, src="ALU", dst="REG_A")]


# SP -> MAR, the two-state prefix every stack access starts with. SP is a
# number, not an address driver (Route B), so MAR does the pointing.
_SP_TO_MAR = [word(src="SP_LO", dst="MAR_LO"),
              word(src="SP_HI", dst="MAR_HI")]


def _PUSH_BYTE(src):
    """Store one byte at [SP], then decrement. Empty-descending."""
    return _SP_TO_MAR + [word(src=src, dst="RAM"), word(misc="SP_DOWN")]


def _PUSH(reg):
    states = _PUSH_BYTE(reg)
    return states[:-1] + [word(misc="SP_DOWN", end=True)]


def _POP(reg):
    """Increment first, THEN load -- the mirror of PUSH's store-then-drop."""
    return ([word(misc="SP_UP")] + _SP_TO_MAR
            + [word(end=True, src="RAM", dst=reg)])


# instruction -> (byte length, [T1, T2, ...]); T0 is implicit FETCH
INSTRUCTIONS = {
    "NOP": (1, [word(end=True)]),
    "LDAI": (2, [word(mux_pc=True, pc_up=True, end=True, src="ROM", dst="REG_A")]),
    "LDBI": (2, [word(mux_pc=True, pc_up=True, end=True, src="ROM", dst="REG_B")]),
    "LDCI": (2, [word(mux_pc=True, pc_up=True, end=True, src="ROM", dst="REG_C")]),
    "LDA": (3, _MARFILL + [word(end=True, src="RAM", dst="REG_A")]),
    "STA": (3, _MARFILL + [word(end=True, src="REG_A", dst="RAM")]),
    "JMP": (3, _MARFILL + [word(end=True, misc="PC_LOAD")]),
    "JNZ": (3, _MARFILL + [word(end=True, misc="COND")]),
    "ADD": (1, _alu("ADD")), "SUB": (1, _alu("SUB")),
    "AND": (1, _alu("AND")), "OR": (1, _alu("OR")),
    "XOR": (1, _alu("XOR")), "CLR": (1, _alu("CLR")),
    "SET": (1, _alu("SET")), "BSUB": (1, _alu("BSUB")),
    "OUT": (1, [word(end=True, misc="REG_OUT_LOAD", src="REG_A")]),
    # IN — the first instruction that makes the machine INTERACTIVE. src=SW
    # enables SWITCH-GATE1 (a plain '244, IS0-7 -> W0-7 unpermuted, both halves
    # on the one ~{SW_OUT} net), and dst=REG_B latches W into B. It also fills
    # the TMP_B shadow, because U50 makes LE_TMP_B = NOR(~{REG_B_LOAD}, CLK) —
    # the latch follows the LOAD STROBE, not the LDBI opcode — so ADD sees the
    # switch byte with no extra row. One byte, so no PC_UP beyond the fetch.
    # SW1 is ACTIVE LOW at the bench: R17-R24 pull IS0-7 high, the switch pulls
    # down, so a CLOSED switch reads 0.
    "IN": (1, [word(end=True, src="SW", dst="REG_B")]),

    # --- the stack ------------------------------------------------------
    #
    # CONVENTION: empty-descending. SP points at the next FREE slot, PUSH
    # stores then decrements, POP increments then loads. A '169 has no
    # clear, so SP is RANDOM at power-up and every program must run LXISP
    # before touching the stack -- "machine works, then randomly doesn't"
    # traced to an unset SP is a miserable afternoon.
    #
    # SP never reaches the address bus directly (Route B). It is just a
    # number; MAR is the thing that points, so every stack access copies
    # SP into MAR first. That costs two T-states per access and buys back
    # the structural guarantee that M has exactly one driver pair.

    # LXISP addr -- the initialiser every program needs first.
    "LXISP": (3, [word(mux_pc=True, pc_up=True, src="ROM", dst="SP_LO"),
                  word(mux_pc=True, pc_up=True, end=True,
                       src="ROM", dst="SP_HI")]),

    "PUSHA": (1, _PUSH("REG_A")), "PUSHB": (1, _PUSH("REG_B")),
    "POPA": (1, _POP("REG_A")), "POPB": (1, _POP("REG_B")),

    # CALL addr -- push the return address, THEN fetch the target.
    #
    # The order is forced: CALL needs two 16-bit values alive at once (the
    # return address and the target) and MAR is the only 16-bit holder, so
    # the push has to finish before MAR is reused to fetch the target.
    #
    # THE PRICE, and it is a real one: what gets pushed is the address of
    # CALL's OPERAND BYTES, not the instruction after them. RET therefore
    # ends with two bare PC_UPs to step over them. Written once here,
    # host-tested, cannot drift.
    "CALL": (3, _PUSH_BYTE("PC_HI") + _PUSH_BYTE("PC_LO") + [
        word(mux_pc=True, pc_up=True, src="ROM", dst="MAR_LO"),
        word(mux_pc=True, pc_up=True, src="ROM", dst="MAR_HI"),
        word(end=True, misc="PC_LOAD"),
    ]),

    # RET -- pop two bytes back into MAR, load the PC from it, then step
    # over the operand bytes per the CALL convention above.
    #
    # The LO byte has to be parked somewhere while MAR is re-pointed at the
    # HI byte's slot, and C is the machine's only free register. That is
    # the whole reason RET clobbers C, and it is why C stays unavailable to
    # user code until a real scratch exists.
    "RET": (1, [
        word(misc="SP_UP"),
        word(src="SP_LO", dst="MAR_LO"),
        word(src="SP_HI", dst="MAR_HI"),
        word(src="RAM", dst="REG_C"),        # return LO parked in C
        word(misc="SP_UP"),
        word(src="SP_LO", dst="MAR_LO"),
        word(src="SP_HI", dst="MAR_HI"),
        # Return HI onto the bus with NO destination -- MDR shadows every W
        # transfer for free (U22 gate2: ~{MDR_EN} = NOR(SRC_ACTIVE, MDR_OUT),
        # so the U25 bridge is on whenever ANY source drives), and LE_MDR =
        # NAND(~{RAM_LOAD}, READS_IDLE) latches that byte the moment the read
        # ends. That gives RET the SECOND scratch it needs without a second
        # register, and it is why src=RAM dst=MAR_HI is NOT used here -- see
        # check_word's RAM-writes-MAR rule.
        word(src="RAM"),
        # REPLAY IMMEDIATELY -- the very next state, before anything else
        # drives MDR. U18's LE_MDR falls as ~{RAM_OUT} deasserts at the
        # T-state boundary, and if another source is turning ON across that
        # same boundary the latch can capture THAT byte instead. Found on the
        # gate model 2026-08-10: with one intervening REG_C -> MAR_LO state,
        # U18 latched C (0x0C) and RET loaded PC = 0x0C0C instead of 0x000C.
        # Reasoning said the park was safe; the model disagreed.
        word(misc="MDR_OUT", dst="MAR_HI"),  # parked HI out of MDR
        word(src="REG_C", dst="MAR_LO"),     # parked LO out of C
        word(misc="PC_LOAD"),                # PC <- M <- MAR
        word(pc_up=True),                    # step over operand byte 1
        word(pc_up=True, end=True),          # step over operand byte 2
    ]),

    "HALT": (1, [word(halt=True)]),
}


# ---- builder asserts (POLICY layer, dino_design_notes.md list) ----------
class BuildError(Exception):
    pass


def _fields(w):
    """(misc, src, dst) as FULL codes, bank bits folded in.

    This MUST fold the bank bits, and the reason is concrete: bank-1 code 10
    (`PC_LO`) has low bits `010`, the same three bits `RAM` uses in bank 0.
    The bank-blind version of this function raised "src=RAM dst=RAM" on
    CALL's push row -- a false positive -- and would just as happily have
    MISSED a genuine bank-1 bus fight. Every rule below compares full codes.
    """
    misc = ((w >> 6) & 7) | (0 if w & MISC_BANK_N else 8)
    src = ((w >> 3) & 7) | (0 if w & SRC_BANK_N else 8)
    dst = (w & 7) | (0 if w & DST_BANK_N else 8)
    return misc, src, dst


def check_word(addr, w):
    """Per-word legality. addr names the row in errors."""
    misc, src, dst = _fields(w)
    where = f"row {addr:#05x} word {w:#06x}"
    # src device == dst device (RAM corrupts; register case is the warning)
    if src == SRC["RAM"] and dst == DST["RAM"]:
        raise BuildError(f"{where}: src=RAM dst=RAM")
    for r in ("REG_A", "REG_B", "REG_C"):
        if src == SRC[r] and dst == DST[r]:
            print(f"WARNING {where}: src=dst={r} (probable MOV typo)")
    # /MDR_OUT replay + ANY source, in EITHER BANK, = two MDR-bus drivers.
    # MISC is an independent field, so this is the one collision the
    # hardware cannot prevent: every SRC-driven buffer is gated by U28 or
    # U70, which are one-hot and mutually exclusive by construction, but
    # U18's ~{MDR_OUT} comes from U29 and can be asserted alongside any of
    # them. Bank 1 widened the set this has to cover from 7 sources to 11.
    if misc == MISC["MDR_OUT"] and src != SRC["NONE"]:
        raise BuildError(f"{where}: /MDR_OUT with src!=NONE (MDR-bus fight)")
    # A RAM READ CANNOT WRITE MAR IN THE SAME WORD. The RAM address IS MAR
    # (U54/U59 -> M), and MAR's '373s are TRANSPARENT while CLK is low -- so
    # src=RAM with dst=MAR_LO/MAR_HI closes a live combinational loop:
    # MAR -> M -> RAM -> MDR -> U25 -> W -> MAR. The address changes
    # underneath the read.
    #
    # Found the hard way on 2026-08-10: RET's first draft did exactly this to
    # get the return address's HI byte into MAR, and the gate model hung with
    # the PC at 0x8D00. Park the byte in MDR instead (src=RAM with NO dst --
    # MDR shadows it for free) and replay it with misc=MDR_OUT.
    #
    # ROM reads are NOT affected: their address comes from the PC through
    # MUX_PC, not from MAR, which is why _MARFILL's ROM->MAR_LO/MAR_HI rows
    # are safe and always have been.
    if src == SRC["RAM"] and dst in (DST["MAR_LO"], DST["MAR_HI"]):
        raise BuildError(f"{where}: src=RAM writing MAR (the address feeds "
                         f"back into the read while the '373 is transparent)")
    # SP cannot count and be read in the same word: the '169s commit on the
    # CLK edge that ENDS the T-state, so the byte on MDR during that state
    # is the PRE-count value while the row reads as though it were the
    # post-count one. Ambiguous by construction -- refuse to encode it.
    if misc in (MISC["SP_UP"], MISC["SP_DOWN"]) and src in (SRC["SP_LO"], SRC["SP_HI"]):
        raise BuildError(f"{where}: SP counted and read in the same word")
    # PC_UP + PC_LOAD same word: defined-but-fragile on '193 internals
    if (w & PC_UP) and misc == MISC["PC_LOAD"]:
        raise BuildError(f"{where}: PC_UP with /PC_LOAD")
    # IR changes only at fetch
    if dst == DST["IR"] and (addr & 0xF) != 0:
        raise BuildError(f"{where}: IR_LOAD outside T0")
    # T0 row of every opcode is the universal fetch
    if (addr & 0xF) == 0 and w != FETCH:
        raise BuildError(f"{where}: T0 row is not the fetch word {FETCH:#06x}")


def check_table(words):
    """Whole-image legality: per-word checks + per-opcode block shape."""
    assert len(words) == 4096
    for a, w in enumerate(words):
        check_word(a, w)
    for op in range(256):
        block = words[op * 16:op * 16 + 16]
        # an instruction must END (or HALT-freeze) before running off its
        # last defined state into safe-fill. Safe-fill is itself END, so
        # scan T1..last-non-fill row: that word must carry END or HALT.
        states = [w for w in block[1:] if w != FILL]
        if states and not (states[-1] & (END | HALT_BIT)):
            raise BuildError(f"opcode {op:#04x}: last state "
                             f"{states[-1]:#06x} has no END/HALT")
        _check_mar_before_ram(op, states)
        _check_mdr_replay_is_immediate(op, states)


def _check_mdr_replay_is_immediate(op, states):
    """misc=MDR_OUT must be the state IMMEDIATELY after the read that parked
    the byte.

    MDR is a genuinely useful second scratch -- U18 shadows every W transfer
    for free -- but the park is only good for ONE state. LE_MDR =
    NAND(~{RAM_LOAD}, READS_IDLE) falls as ~{RAM_OUT} deasserts at the
    T-state boundary, and if another source is turning ON across that same
    boundary the latch can capture THAT byte instead. It is a race, not a
    rule, so it cannot be reasoned about from the gate equations alone.

    Paid for on 2026-08-10: RET's second draft parked the return address's HI
    byte in MDR, moved the LO byte from C to MAR_LO, and only THEN replayed.
    U18 latched C, MAR_HI got 0x0C instead of 0x00, and RET loaded the PC
    with 0x0C0C. Every reading of the schematic said the park was safe; the
    gate model disagreed, which is the whole reason the FPGA is the primary
    instrument now.
    """
    for t, w in enumerate(states, start=1):
        misc, src, _ = _fields(w)
        if misc != MISC["MDR_OUT"]:
            continue
        if t < 2:
            raise BuildError(f"opcode {op:#04x} T{t}: MDR_OUT with no prior "
                             f"state to have parked a byte")
        prev_misc, prev_src, _ = _fields(states[t - 2])
        if prev_src not in (SRC["ROM"], SRC["RAM"]):
            raise BuildError(
                f"opcode {op:#04x} T{t}: MDR_OUT replays a byte that was not "
                f"parked by the IMMEDIATELY preceding state (T{t-1} has "
                f"src={prev_src}, needs ROM or RAM) -- MDR holds for exactly "
                f"one state, see _check_mdr_replay_is_immediate")


def _check_mar_before_ram(op, states):
    """A RAM access must be preceded, in the SAME instruction, by BOTH MAR
    halves being loaded.

    The hardware already prevents the dangerous case -- ~{RAM_WRITE_EN} =
    NAND(~{CLK}, WRITE_DIR) and WRITE_DIR = NOT(~{RAM_LOAD}), so no write
    strobe exists on a row whose DST is not RAM, and the half-updated MAR
    that occurs on EVERY memory instruction (_MARFILL loads LO at T1, HI at
    T2) can never fire one.

    What the hardware cannot prevent is MICROCODE authored in the wrong
    order: a row with DST=RAM before both halves are set writes to a real
    address, in the wrong place, silently. That is exactly the shape a PUSH
    sequence typed one T-state out of order would take, and the stack made
    it worth policing rather than leaving incidental.
    """
    lo = hi = False
    for t, w in enumerate(states, start=1):
        _, src, dst = _fields(w)
        if dst == DST["MAR_LO"]: lo = True
        if dst == DST["MAR_HI"]: hi = True
        if (src == SRC["RAM"] or dst == DST["RAM"]) and not (lo and hi):
            raise BuildError(
                f"opcode {op:#04x} T{t}: RAM accessed with MAR incomplete "
                f"(MAR_LO={'set' if lo else 'UNSET'}, "
                f"MAR_HI={'set' if hi else 'UNSET'})")


# Instructions whose PC_UP count is deliberately NOT their byte length,
# each with the reason. An exemption has to be named here to be silent --
# the check still polices everything else.
_PC_UP_EXEMPT = {
    "RET": "1 byte, 3 PC_UPs: the fetch plus two bare steps over CALL's "
           "operand bytes. CALL pushes the address of its OPERANDS (MAR is "
           "the only 16-bit holder, so the push must finish before the "
           "target fetch reuses it), and stepping over them is the price.",
}


def _check_lengths():
    for name, (nbytes, states) in INSTRUCTIONS.items():
        ups = sum(1 for w in [FETCH] + states if w & PC_UP)
        if ups != nbytes and name not in _PC_UP_EXEMPT:
            print(f"WARNING {name}: PC_UP count {ups} != byte length {nbytes}")


# ---- images -------------------------------------------------------------
def build_real():
    words = [FILL] * 4096
    for op in range(256):
        words[op * 16] = FETCH
    for name, (_, states) in INSTRUCTIONS.items():
        base = OPCODES[name] * 16
        for t, w in enumerate(states, start=1):
            words[base + t] = w
    _check_lengths()
    check_table(words)
    return words


def build_diag():
    return [a | ((~(a >> 8) & 0xF) << 12) for a in range(4096)]


def diag_third(words):
    """U23's diagnostic byte.

    `U9_diag` carries a[7:0] and `U15_diag` carries a[11:8] plus its inverse.
    The third ROM has NO address bits left, so a constant fill would leave
    eight data lines that no sweep exercises -- the same problem CW12-15 had,
    eight times over.

        U23_diag[a] = ~(((a >> 4) & 0xFF) ^ (a & 0x0F))

    A4-A11 reach bits 0-7 through `a >> 4`; A0-A3 reach bits 0-3 through
    `a & 0xF`. Every one of the twelve address lines affects the byte, every
    one of the eight data lines takes both values, and the pattern is distinct
    from both other chips so a swapped-ROM fault cannot alias.

    REJECTED EARLIER RULE, recorded so it is not re-proposed: `~((a >> 4) &
    0xFF)` alone. Address = {IR[7:0], T[3:0]}, so `a >> 4` IS `IR` exactly and
    the byte never varies with T -- it cannot detect a swap among MCA0-MCA3,
    which is precisely the fault class a diag image exists to catch.
    """
    return bytes((~(((a >> 4) & 0xFF) ^ (a & 0x0F))) & 0xFF
                 for a in range(len(words)))


def crc16(data):
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF. Mirrors src/crc16.c."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


# U23's byte, CW16-23 -- the third EEPROM, schematic 2026-08-10.
#
# EVERY new field is polarised so 0xFF is TODAY'S MACHINE:
#
#   CW16 ~{CIN_SEL}    1 = the existing NOT(SA1 AND SA0) carry path
#   CW17 ~{SRC_BANK}   1 = SRC bank 0 (U28 enabled via E3, U70 dark via E1)
#   CW18 ~{DST_BANK}   1 = DST bank 0
#   CW19 ~{MISC_BANK}  1 = MISC bank 0        (unwired, in reserve)
#   CW20 ~{ADDR_SEL1}  1 = ADDR_SEL1 low, CW14 alone picks MAR/PC (unwired)
#   CW21 FLAG_SEL0  \
#   CW22 FLAG_SEL1   > don't-care unless MISC=COND is decoded  (unwired)
#   CW23 FLAG_POL   /
#
# So an ERASED AT28C64B is a valid U23 image, and that is not a coincidence
# -- it is the property the polarities were chosen for (same reasoning that
# made HALT=0xFF). Until the fields are actually encoded, THIRD = 0xFF is the
# correct image, not a placeholder: it reproduces the 16-bit machine exactly.
#
# The one row that will differ once FLAG_SEL/FLAG_POL are encoded is JNZ's
# MISC=COND T-state (FLAG_SEL=Z, FLAG_POL=1 -> 0xBF), matching today's
# COND_TAKEN = NOR(~{COND}, FLAG_Z). The COND hardware ('153 + '86) does not
# exist yet, so 0xFF is correct for it too right now.
THIRD_INERT = 0xFF


def third(words):
    """U23 = word[23:16] = CW16-23."""
    return bytes((w >> 16) & 0xFF if w > 0xFFFF else THIRD_INERT
                 for w in words)


def split(words):
    lo = bytes(w & 0xFF for w in words)      # U9  = CW0-7
    hi = bytes((w >> 8) & 0xFF for w in words)   # U15 = CW8-15
    return lo, hi


def _mirror(half):                            # A12 grounded: 2x the image
    return half + half


def emit_header(real, crcs, path):
    lines = [
        "/* GENERATED by microcode_gen.py — do not hand-edit.",
        "   Regenerate: python3 docs/notes/microcode_gen.py */",
        "#ifndef MICROCODE_EXPECT_H",
        "#define MICROCODE_EXPECT_H",
        "#ifdef __AVR__",
        "#include <avr/pgmspace.h>",
        "#else",
        "#define PROGMEM",
        "#endif",
        "#include <stdint.h>",
        "",
        "/* image-detect signatures: row 0 of each burn */",
        f"#define MC_REAL_ROW0 0x{real[0]:06X}UL",
        f"#define MC_DIAG_ROW0 0x{build_diag()[0]:04X}",
        "",
        "/* CRC-16/CCITT-FALSE over the 4096 addressable bytes per chip */",
    ]
    for name, val in crcs.items():
        lines.append(f"#define {name} 0x{val:04X}")
    lines += [
        "",
        "/* diag word is a pure function of its row (test spec, ROM images):",
        "   addr[11:0] in the data, INVERTED addr[11:8] in [15:12] */",
        "#define MC_DIAG_WORD(a) ((uint16_t)(((a) & 0x0FFF) | "
        "((uint16_t)(~((a) >> 8) & 0xF) << 12)))",
        "",
        "/* the shipped real image, row-addressable for bench diagnostics.",
        "   24 BITS since 2026-08-10 -- U23 carries CW16-23, so a uint16_t",
        "   here would silently truncate every bank bit. */",
        "static const uint32_t MC_REAL_WORDS[4096] PROGMEM = {",
    ]
    for i in range(0, 4096, 8):
        row = ", ".join(f"0x{w:06X}UL" for w in real[i:i + 8])
        lines.append(f"    {row},")
    # THE IMPLEMENTED OPCODE LIST. Cannot be inferred from the image: T0 is
    # the universal FETCH row for ALL 256 opcodes, and NOP's T1 is a bare END
    # identical to the FILL written at every unimplemented opcode. A rig that
    # guesses "is this opcode real?" from the words will walk all 256 and
    # compare 238 of them against fill. (Cost one Block 1 bench run to learn,
    # 2026-07-30.)
    ops = sorted(OPCODES.items(), key=lambda kv: kv[1])
    lines += [
        "};",
        "",
        "/* Every opcode the microcode actually implements, ascending. */",
        f"#define MC_OPCODE_COUNT {len(ops)}u",
        "static const uint8_t MC_OPCODES[MC_OPCODE_COUNT] PROGMEM = {",
        "    " + ", ".join(f"0x{v:02X}" for _n, v in ops) + ",",
        "};",
        "",
        "/* Opcodes whose last row carries HALT instead of END. END-segmented",
        "   capture cannot bracket these — the sequencer stops. */",
        "#define MC_HALT_OPCODE 0x%02Xu" % OPCODES["HALT"],
        "",
        "#endif", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    real, diag = build_real(), build_diag()
    os.makedirs(ROMS, exist_ok=True)
    crcs = {}
    for tag, words in (("REAL", real), ("DIAG", diag)):
        lo, hi = split(words)
        thd = third(words) if tag == "REAL" else diag_third(words)
        for chip, half in (("U9", lo), ("U15", hi), ("U23", thd)):
            fn = f"{chip}.bin" if tag == "REAL" else f"{chip}_diag.bin"
            with open(os.path.join(ROMS, fn), "wb") as f:
                f.write(_mirror(half))
            crcs[f"MC_CRC_{chip}_{tag}"] = crc16(half)
    emit_header(real, crcs, HDR)
    print(f"wrote 6x 8192B bins -> {ROMS}")
    print(f"wrote expect header -> {HDR}")
    print("burn order: DIAG set first (addr/split tests), REAL set second")
    print("  U9  = word[7:0]   = CW0-7   (low byte)")
    print("  U15 = word[15:8]  = CW8-15  (high byte)")
    print("  U23 = word[23:16] = CW16-23 (third ROM)")
    print("  ALL THREE need burning when an INSTRUCTION is added or changed:")
    print("  a new opcode writes rows in every byte of the word. U9/U15 stay")
    print("  untouched only for changes confined to CW16-23.")
    for name, val in crcs.items():
        print(f"  {name} = 0x{val:04X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
