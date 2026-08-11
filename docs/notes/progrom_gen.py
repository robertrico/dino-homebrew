#!/usr/bin/env python3
"""DINO program ROM image generator (AT28C256, 32KB, ROM 0x0000-0x7FFF).

Emits roms/PROG.bin (the real program) + roms/PROG_diag.bin (the
address-proof image), their CRC16s, and the rig's expect header
(tests/dino_bringup/src/progrom_expect.h) so rig and ROM can never
disagree — same contract microcode_gen.py holds for the microcode pair.

OPCODES and instruction LENGTHS are imported from microcode_gen: one
source of truth. The assembler validates every operand count against the
microcode table, so a program can never encode an instruction the
microcode cannot execute.

DIAG image (memory.rom.order): content-addressed and SELF-NAMING —
  addr 0    -> 0xA5 marker
  addr 2^k  -> 0x40|k  (k = 0..14)   <- a mis-decoded address line reports
                                        the address the chip ACTUALLY saw
  else      -> multiplicative hash, so every other row is distinctive too
15 address lines is a lot of one-hole opportunity; this retires the
mirror/swap/stuck class the way the microcode diag burn did.

REAL image: the MILESTONE program (hard gate — the machine adds two
numbers), safe-filled with HALT so an erased or overrun ROM halts
instead of raving.

Run:  python3 progrom_gen.py          (writes roms/ + expect header)
Test: python3 test_progrom_gen.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from microcode_gen import (OPCODES, INSTRUCTIONS, DST, SRC, MISC,  # noqa: E402
                           SA, _sa_bits)                         # single source

HERE = os.path.dirname(os.path.abspath(__file__))
ROMS = os.path.normpath(os.path.join(HERE, "..", "..", "roms"))
HDR = os.path.normpath(os.path.join(
    HERE, "..", "..", "tests", "dino_bringup", "src", "progrom_expect.h"))

SIZE = 32768                    # AT28C256, ROM half of the memory map
SAFE_FILL = OPCODES["HALT"]     # erased/overrun ROM must HALT, never rave

# ---- diag image ---------------------------------------------------------
DIAG_ZERO = 0xA5                # address 0 marker (also the burn signature)
DIAG_WALK = 0x40                # 2^k -> DIAG_WALK|k, k = 0..14
WITNESS_ADDRS = [0] + [1 << k for k in range(15)]


def diag_byte(addr):
    """Content-addressed diag value. Self-naming on the witness set."""
    addr &= SIZE - 1
    if addr == 0:
        return DIAG_ZERO
    if addr & (addr - 1) == 0:                  # exact power of two
        return DIAG_WALK | addr.bit_length() - 1
    return ((addr * 0x9D) ^ (addr >> 5)) & 0xFF


def build_diag():
    return bytes(diag_byte(a) for a in range(SIZE))


# ---- the milestone program ---------------------------------------------
# HARD GATE (Rico): no ISA/hardware extensions until the whole machine
# adds two numbers. This is that program — load, add, expose, halt.
#
# The addends are 0x2F and 0x1E, not 5 and 3. 5+3=8 was the first sum this
# machine ever produced, and it is a thin witness: one bit set, low nibble
# only, one carry. It cannot see a stuck or swapped bit in the upper nibble at
# all. 0x2F + 0x1E = 0x4D sets bits in BOTH nibbles of both addends and of the
# answer, and the carry ripples from bit 1 through bit 6 — crossing bit 3->4,
# where the two '382s hand over to each other.
ADDEND_A = 0x2F
ADDEND_B = 0x1E
EXPECT_SUM = ADDEND_A + ADDEND_B        # 0x4D = 0b01001101

#
# THE PROGRAM POISONS OB BEFORE IT COMPUTES. U35 has no reset and the machine
# free-runs at power-up, so OB always already holds the previous run's answer —
# power-cycling does not clear it. A test that reads OB after a reset therefore
# cannot tell a fresh result from a leftover, and the rig spent several bench
# runs printing INCONCLUSIVE (or worse, PASS on a stale byte).
#
# Writing 0xFF to OB as the FIRST thing the program does removes the ambiguity
# at the source: any run that so much as STARTS destroys the old answer. OB can
# only read 0x4D if THIS run reached the second OUT. A machine that dies partway
# leaves 0xFF sitting there instead of impersonating success.
POISON = 0xFF

PROGRAM = [
    ("LDAI", POISON),       # A = 0xFF
    ("OUT",),               # OB <- 0xFF: the previous answer is now GONE
    ("LDAI", ADDEND_A),     # A = 0x2F  (also latches TMP_A shadow)
    ("LDBI", ADDEND_B),     # B = 0x1E  (also latches TMP_B shadow)
    ("ADD",),               # A = TMP_A + TMP_B = 0x4D, flags commit
    ("OUT",),               # OB <- 0x4D, LEDs show the sum
    ("HALT",),              # park: T-counter frozen, clock still running
]


class BuildError(Exception):
    pass


class Ref:
    """A forward/backward label reference. Expands to two operand bytes,
    LO then HI, so it satisfies the microcode's declared length for the
    MAR-consuming instructions (LDA/STA/JMP/JNZ)."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Ref({self.name!r})"


def assemble(program, base=0):
    """Symbolic steps -> bytes. Operand count and range are validated
    against the microcode table's declared instruction length; operands
    are emitted LO then HI (little-endian, 8008 lineage).

    A bare string in the step list is a LABEL definition. A Ref in an
    operand position is a label reference and counts as TWO operands,
    which is what the _MARFILL prefix fetches."""
    # pass 1 — addresses. Instruction lengths come from the microcode table,
    # never from a retyped constant.
    addr, labels = base, {}
    for step in program:
        if isinstance(step, str):
            if step in labels:
                raise BuildError(f"duplicate label {step!r}")
            labels[step] = addr
            continue
        name = step[0]
        if name not in OPCODES or name not in INSTRUCTIONS:
            raise BuildError(f"unknown mnemonic {name!r}")
        addr += INSTRUCTIONS[name][0]

    # pass 2 — emit
    out = bytearray()
    for step in program:
        if isinstance(step, str):
            continue
        name, operands = step[0], list(step[1:])
        flat = []
        for v in operands:
            if isinstance(v, Ref):
                if v.name not in labels:
                    raise BuildError(f"{name}: undefined label {v.name!r}")
                a = labels[v.name]
                flat += [a & 0xFF, (a >> 8) & 0xFF]
            else:
                flat.append(v)
        want = INSTRUCTIONS[name][0] - 1        # length includes the opcode
        if len(flat) != want:
            raise BuildError(
                f"{name}: {len(flat)} operands, microcode declares {want}")
        for v in flat:
            if not 0 <= v <= 0xFF:
                raise BuildError(f"{name}: operand {v} out of byte range")
        out.append(OPCODES[name])
        out.extend(flat)
    return bytes(out)


# ---- interpreter: driven BY THE MICROCODE, not by a restatement of it ----
# Every semantic below is read out of the burned microcode word, so the
# expectation and the hardware cannot disagree. Same discipline as
# cw_expect/MC_REAL_WORDS on the rig side: no eleventh table.
_DST = {v: k for k, v in DST.items()}
_SRC = {v: k for k, v in SRC.items()}
_MISC = {v: k for k, v in MISC.items()}
_SA = {v: k for k, v in SA.items()}
from microcode_gen import SRC_BANK_N, DST_BANK_N, MISC_BANK_N  # noqa: E402

RAM_BASE = 0x8000       # M15 selects: ROM 0x0000-0x7FFF, RAM 0x8000-0xFFFF

# Deliberately not 0x0000: see simulate()'s own comment. Points into ROM
# space, so a stack access before LXISP writes nowhere and reads program
# bytes -- loudly wrong rather than quietly plausible.
SP_POISON = 0x5A5A


def sim_supports(name):
    """Can the interpreter execute every row of this instruction?"""
    if name not in INSTRUCTIONS:
        return False
    for w in INSTRUCTIONS[name][1]:
        if _DST.get(w & 7) is None or _SRC.get((w >> 3) & 7) is None:
            return False
        if _MISC.get((w >> 6) & 7) is None:
            return False
    return True


def _alu_op(op, a, b):
    if op == "CLR":
        return 0, 0
    if op == "SET":
        return 0xFF, 0
    if op == "ADD":
        r = a + b
        return r & 0xFF, (r >> 8) & 1
    if op == "SUB":
        r = a - b
        return r & 0xFF, 1 if r < 0 else 0
    if op == "BSUB":
        r = b - a
        return r & 0xFF, 1 if r < 0 else 0
    if op == "XOR":
        return a ^ b, 0
    if op == "OR":
        return a | b, 0
    if op == "AND":
        return a & b, 0
    raise BuildError(f"interpreter has no model for SA={op}")


def simulate(program, max_steps=100000, switches=0x00):
    """Execute an assembled image by interpreting its microcode rows.

    Returns a dict of observables. `out` is what OB would read — the only
    datapath observable the block ladder has, which is why every coverage
    image ends OUT; HALT."""
    code = assemble(program)
    poison = {i for i, _ in _poison_spans(program)}
    ram = {}
    A = B = C = 0
    tmp_a = tmp_b = 0
    pc = 0
    mar = 0
    # A '169 has NO CLEAR, so SP is random at power-up on real silicon and
    # every program must run LXISP first. Starting the oracle at 0 would be
    # KINDER THAN THE HARDWARE and would let a program that forgot LXISP
    # agree with the model and then fail on the bench -- the same trap the
    # '169 VHDL model's por_value generic exists to avoid.
    sp = SP_POISON
    mdr = 0
    out = None
    flag_z = 0
    st = {"ram_writes": 0, "ram_reads": 0, "branches_taken": 0,
          "branches_not_taken": 0, "hit_poison": False, "stored": None,
          "steps": 0, "ends": 0}

    def rd(a):
        if a < SIZE:
            return code[a] if a < len(code) else SAFE_FILL
        return ram.get(a, 0)

    while st["steps"] < max_steps:
        st["steps"] += 1
        if pc in poison:
            st["hit_poison"] = True
        op = rd(pc)
        pc = (pc + 1) & 0xFFFF                      # T0 FETCH: IR <- ROM, PC++
        name = {v: k for k, v in OPCODES.items()}.get(op)
        if name is None or name not in INSTRUCTIONS:
            raise BuildError(f"pc=0x{pc-1:04X}: no instruction for 0x{op:02X}")
        for w in INSTRUCTIONS[name][1]:
            # BANK-AWARE DECODE. `(w >> 3) & 7` alone is wrong since the
            # third EEPROM landed: bank-1 code 10 (PC_LO) has the same low
            # three bits as bank-0 code 2 (RAM), so a bank-blind oracle would
            # read a PC push as a RAM read and agree with nothing. Same fault
            # class check_word had, and it is worth stating plainly because
            # both the coverage images and the differential fuzz harness
            # trust this function as ground truth.
            src = _SRC[((w >> 3) & 7) | (0 if w & SRC_BANK_N else 8)]
            dst = _DST[(w & 7) | (0 if w & DST_BANK_N else 8)]
                # CW9..CW11 hold the '382 code BIT-REVERSED — CW9 is labelled SA2
            # and wired to the chip's select MSB. _sa_bits is its own inverse,
            # so the same call unpacks it. Reading the field raw here would
            # make the interpreter compute AND where the hardware computes ADD,
            # which is the very fault this encoding change fixes.
            misc = _MISC[((w >> 6) & 7) | (0 if w & MISC_BANK_N else 8)]
            sa = _SA[_sa_bits((w >> 9) & 7)]
            halt, pc_up = (w >> 15) & 1, (w >> 13) & 1

            val = None
            if src == "ROM":
                val = rd(pc)
            elif src == "RAM":
                val = rd(mar)
                st["ram_reads"] += 1
            elif src == "REG_A":
                val = A
            elif src == "REG_B":
                val = B
            elif src == "REG_C":
                val = C
            elif src == "SW":
                val = switches
            elif src == "SP_LO":
                val = sp & 0xFF
            elif src == "SP_HI":
                val = (sp >> 8) & 0xFF
            elif src == "PC_LO":
                # PC0-15 is tapped at the '193 outputs (U72/U73), NOT off the
                # M bus -- so this reads the PC whatever the address mux is
                # doing, which is exactly what CALL needs while MAR points at
                # the stack slot.
                val = pc & 0xFF
            elif src == "PC_HI":
                val = (pc >> 8) & 0xFF
            elif misc == "MDR_OUT":
                # MDR replay. U18 holds whatever last crossed the bus, and
                # LE_MDR = NAND(~{RAM_LOAD}, READS_IDLE) latches it as soon
                # as the read ends -- so it is a free second scratch, which
                # is exactly what RET uses to carry the return address's HI
                # byte while MAR is re-pointed.
                val = mdr

            # MDR is a TRANSPARENT LATCH, not a register that samples every
            # transfer:
            #     LE_MDR   = NAND(~{RAM_LOAD}, READS_IDLE)      U39 gate2
            #     READS_IDLE = AND(~{ROM_OUT}, ~{RAM_OUT})      U39 g1 + U37
            # so it follows the bus ONLY during a memory read or a RAM write,
            # and HOLDS otherwise.
            #
            # Modelling it as "shadows everything" is wrong and was wrong
            # here first: RET parks the return address's HI byte in MDR and
            # then moves the LO byte from C to MAR_LO. With an over-eager
            # shadow that register-to-register move clobbers the parked byte,
            # MAR_HI gets 0x0C instead of 0x00, and the return lands in the
            # weeds -- which is exactly what the oracle reported before this
            # was corrected.
            if val is not None and (src in ("ROM", "RAM") or dst == "RAM"):
                mdr = val
            elif src == "ALU":
                val, _c = _alu_op(sa, tmp_a, tmp_b)
                flag_z = 1 if val == 0 else 0       # U48 mux: commits only
                                                    # while ~{ALU_OUT} is low
            if pc_up:
                pc = (pc + 1) & 0xFFFF

            if dst == "REG_A":
                A = val
                tmp_a = val                         # TMP_A restamps on A load
            elif dst == "REG_B":
                B = val
                tmp_b = val
            elif dst == "REG_C":
                C = val
            elif dst == "MAR_LO":
                mar = (mar & 0xFF00) | val
            elif dst == "MAR_HI":
                mar = (mar & 0x00FF) | (val << 8)
            elif dst == "RAM":
                ram[mar] = val
                st["ram_writes"] += 1
                st["stored"] = val
            elif dst == "SP_LO":
                sp = (sp & 0xFF00) | val
            elif dst == "SP_HI":
                sp = (sp & 0x00FF) | (val << 8)

            if misc == "PC_CLEAR":
                pc = 0
            elif misc == "PC_LOAD":
                pc = mar
            elif misc == "COND":
                # COND_TAKEN = NOR(~{COND}, FLAG_Z): taken when NOT zero
                if not flag_z:
                    pc = mar
                    st["branches_taken"] += 1
                else:
                    st["branches_not_taken"] += 1
            elif misc == "REG_OUT_LOAD":
                out = A
            elif misc == "SP_UP":
                sp = (sp + 1) & 0xFFFF
            elif misc == "SP_DOWN":
                sp = (sp - 1) & 0xFFFF

            if halt:
                st.update(out=out, halted=True, A=A, B=B, C=C, flag_z=flag_z)
                return st
            if (w >> 12) & 1:                       # END
                st["ends"] += 1
                break
    st.update(out=out, halted=False, A=A, B=B, C=C, flag_z=flag_z)
    return st


def _poison_spans(program):
    """Addresses of labels named `poison*` — code a correct machine must
    never reach. The flow image uses one to prove the JMP actually jumped
    rather than merely falling through to the same place."""
    addr, spans = 0, []
    for step in program:
        if isinstance(step, str):
            if step.startswith("poison"):
                spans.append((addr, 1))
            continue
        addr += INSTRUCTIONS[step[0]][0]
    return spans


# ---- progressive ISA-coverage images ------------------------------------
# The block ladder proves the machine EXECUTES. These prove it executes the
# WHOLE of the current ISA. Each image ends OUT; HALT because OB is the only
# datapath observable on the ladder, and each answer is chosen so its
# BIT-REVERSED read is a different byte — the flipped-ribbon fault that only
# registers.outreg ever caught (mirror-witness rule).
#
# Earliest block each can run at:
#   flow  -> block 3   (JMP needs MAR loaded from ROM through the U25 bridge;
#                       witnessed on the IRB opcode stream)
#   alu   -> block 4   (needs real registers + a real ALU)
#   mem   -> block 4   (RAM round-trip, witnessed on OB)
#   loop  -> block 4   (needs a real FLAG_Z for the JNZ taken arm)
#
# NOTE for blocks 1-3: FLAG_Z is STRAPPED HIGH, so COND_TAKEN is pinned low
# and JNZ is NEVER taken there. Block 3 exercises JMP and the NOT-TAKEN arm
# only; the taken arm needs a real ALU flag and therefore block 4.

RAM_SCRATCH = RAM_BASE          # first RAM byte, past the M15 boundary
RAM_ACC = RAM_BASE + 1
RAM_CNT = RAM_BASE + 2


def _addr(a):
    return (a & 0xFF, (a >> 8) & 0xFF)


# alu — every one of the eight SA codes, chained so a wrong code corrupts
# the final signature rather than being masked by a later operation.
ALU_PROGRAM = [
    ("LDAI", 0x5A), ("LDBI", 0x3C),
    ("XOR",),               # A = 0x5A ^ 0x3C = 0x66
    ("OR",),                # A = 0x66 | 0x3C = 0x7E
    ("AND",),               # A = 0x7E & 0x3C = 0x3C
    ("ADD",),               # A = 0x3C + 0x3C = 0x78
    ("SUB",),               # A = 0x78 - 0x3C = 0x3C
    ("BSUB",),              # A = 0x3C - 0x3C = 0x00
    ("SET",),               # A = 0xFF   (both rails touched, deliberately)
    ("CLR",),               # A = 0x00
    ("LDBI", 0x39), ("OR",),   # A = 0x39 — a witness, not a rail
    ("OUT",), ("HALT",),
]

# mem — absolute store then load-back through RAM. This is ALSO the
# MAR-AS-LATCH witness: LDA/STA are the only instructions that load MAR, and
# the milestone contains none of them (see BRINGUP.md block 2 named gap).
MEM_PROGRAM = [
    ("LDAI", 0xC5),
    ("STA", *_addr(RAM_SCRATCH)),
    ("LDAI", 0x00),                     # clobber A so the read-back is real
    ("LDA", *_addr(RAM_SCRATCH)),
    ("OUT",), ("HALT",),
]

# flow — JMP over a poison byte, then a JNZ that must NOT be taken.
FLOW_PROGRAM = [
    ("JMP", Ref("main")),
    "poison_never",
    ("HALT",),                          # reaching this means the JMP failed
    "main",
    ("LDAI", 0x01), ("LDBI", 0x01),
    ("SUB",),                           # A = 0 -> Z set
    ("JNZ", Ref("bad")),                # must fall through
    ("LDAI", 0x39), ("OUT",), ("HALT",),
    "bad",
    ("LDAI", 0xE7), ("OUT",), ("HALT",),
]

# loop — the JNZ TAKEN arm, iterating an exact number of times. The counter
# lives in RAM because there is no third register to spare: C is write-only
# until MOV exists. A wrong iteration count changes the accumulator, so the
# answer proves the count rather than merely proving the loop exited.
LOOP_N = 3
LOOP_STEP = 7
LOOP_EXPECT = LOOP_N * LOOP_STEP        # 21 = 0x15, mirror 0xA8

LOOP_PROGRAM = [
    ("LDAI", LOOP_N), ("STA", *_addr(RAM_CNT)),
    ("LDAI", 0x00), ("STA", *_addr(RAM_ACC)),
    "loop",
    ("LDA", *_addr(RAM_ACC)), ("LDBI", LOOP_STEP), ("ADD",),
    ("STA", *_addr(RAM_ACC)),
    ("LDA", *_addr(RAM_CNT)), ("LDBI", 0x01), ("SUB",),
    ("STA", *_addr(RAM_CNT)),           # flags HOLD across STA (U48.1 =
                                        # ~{ALU_OUT}), which is what makes
                                        # this loop writable at all
    ("JNZ", Ref("loop")),
    ("LDA", *_addr(RAM_ACC)),
    ("OUT",), ("HALT",),
]

# stack — the witness for the whole 2026-08-10 addition: LXISP, PUSH, POP,
# CALL and RET, plus the bank-1 SRC/DST codes and the third EEPROM's two
# wired bits. Nothing else in the coverage set can reach any of them.
#
# SP must be initialised before anything touches the stack: a '169 has NO
# CLEAR, so SP is RANDOM at power-up. LXISP is therefore the first
# instruction, not a nicety.
#
# The stack lives at the TOP of RAM and grows DOWN (empty-descending: SP
# points at the next free slot, PUSH stores then decrements). RAM_ACC/RAM_CNT
# sit at the BOTTOM, so a stack that runs away collides with them loudly
# rather than silently overwriting the answer.
#
# ONE OUT, AND IT IS THE LAST INSTRUCTION BEFORE HALT. OB is the only
# datapath observable the coverage harness reads, and it reads it at halt --
# so an earlier OUT would let a BROKEN CALL/RET leave a correct-looking value
# behind. The single OUT sits after the return, and the value is computed
# INSIDE the subroutine, so reaching it at all proves the return address was
# pushed, stored, popped back and loaded into the PC.
#
# THE ANSWER PROVES ORDER, NOT MERELY SURVIVAL. Two DIFFERENT bytes go in and
# come back into SWAPPED registers, and the subroutine SUBTRACTS rather than
# adds -- a sum is order-independent and would pass with the bytes reversed.
#     correct LIFO   0x53 - 0x2C = 0x27
#     wrong order    0x2C - 0x53 = 0xD9
# That is the mirror-witness rule applied to the stack. A push-then-pop round
# trip with ONE value is self-consistent under a crossed ~TC cascade, a stuck
# direction pin, and a nibble-reversed readback alike -- all three of which
# are live failure modes here.
STACK_TOP = RAM_BASE + 0xFF
STACK_PUSH_A = 0x2C
STACK_PUSH_B = 0x53
# A - B after a CORRECT LIFO round trip. SUB, not ADD, on purpose: a sum is
# order-independent, so it would pass with the two bytes swapped. 0x53-0x2C
# and 0x2C-0x53 are 0x27 and 0xD9 -- a wrong order names itself.
STACK_EXPECT = (STACK_PUSH_B - STACK_PUSH_A) & 0xFF   # 0x27

STACK_PROGRAM = [
    ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),
    ("LDAI", STACK_PUSH_A),
    ("LDBI", STACK_PUSH_B),
    ("PUSHA",),
    ("PUSHB",),
    ("POPA",),                          # LIFO: A <- what B pushed = 0x53
    ("POPB",),                          #       B <- what A pushed = 0x2C
    ("CALL", Ref("sub")),
    ("OUT",),                           # the ONLY OUT -- see below
    ("HALT",),
    "sub",
    ("SUB",),                           # A = A - B, computed INSIDE the call
    ("RET",),
]

# ---- DIAGNOSTIC images for the 2026-08-03 PROG_flow failure -------------
# PROG_flow ran as a 2-instruction loop forever: 4-state, 2-state, 66 ENDs, no
# HALT, OB never written. Working backwards from that trace, the cycle can ONLY
# be SUB@0x0008 <-> JNZ@0x0009 (the single place in the image where a 2-state
# instruction is immediately followed by a 4-state one), so BOTH jumps landed at
# 0x0008 — and 0x0008 is the unique landing value that reproduces the trace.
#
#     JMP wanted MAR=0x0004  -> PC went to 0x0008
#     JNZ wanted MAR=0x0010  -> PC went to 0x0008
#
# Two distinct inputs, one output: the fault is LOSSY (stuck or dead bits), not
# a permutation, so the swapped-ribbon class is ruled out by arithmetic.
#
# PROG_mem passes anyway, and CANNOT do otherwise. Its only MAR value is
# RAM_SCRATCH = 0x8000 — bit 15 alone, every other MAR bit zero — and it uses
# the SAME address for the store and the load. A MAR_LO stuck at 0x08 simply
# moves mem's scratch cell to 0x8008 and the round trip still returns 0xC5.
# That is the mirror-witness rule cashed in: write-then-read through one address
# is blind to what that address actually was.
#
# The rig cannot help here. mar.logic and pc.load are MODULE tests — they
# bus_w_write(), bus_m_drive() and drive the load strobes directly, ~28 driven
# wires into live '245s and '138 outputs on a fully seated machine. The block
# law only runs one direction and the driven count may never go up. So these
# two images are the whole instrument: the ROM socket adds no wires at all.

MARDISC_A = RAM_BASE + 0x04     # the two addresses flow actually fed to MAR,
MARDISC_B = RAM_BASE + 0x10     # in the low byte where the fault must live
MARDISC_VA = 0x6B               # answer if MAR_LO discriminates
MARDISC_VB = 0x2D               # answer if it collapses them to one cell

# mardisc — DOES MAR_LO DISCRIMINATE ADDRESSES AT ALL? Two stores to addresses
# that differ ONLY in MAR_LO, then read the FIRST one back. If the low byte is
# stuck, both stores landed in the same cell and the read returns the SECOND
# value. No jumps anywhere, so this runs and answers regardless of the PC_LOAD
# fault. It asks the one question PROG_mem is structurally unable to ask.
#
#     OB = 0x6B   MAR_LO is fine, the cells stayed distinct -> fault downstream
#     OB = 0x2D   0x04 and 0x10 collapsed -> MAR_LO is the fault
#     OB = 0xFF   never finished (the leading poison, as in the milestone)
MARDISC_PROGRAM = [
    ("LDAI", POISON), ("OUT",),         # destroy the previous answer first
    ("LDAI", MARDISC_VA), ("STA", *_addr(MARDISC_A)),
    ("LDAI", MARDISC_VB), ("STA", *_addr(MARDISC_B)),
    ("LDA", *_addr(MARDISC_A)),         # if MAR_LO is stuck this reads VB
    ("OUT",), ("HALT",),
]

# pads — WHERE DOES THE PC ACTUALLY LAND? A landing-pad grid, self-naming the
# way the diag image is: every 4-byte slot holds `LDAI <own address>; OUT; HALT`
# so OB reports the address the PC really loaded. Only worth burning if mardisc
# says MAR_LO is healthy, because then the fault is downstream in
# M -> U11/U12 -> PCD -> the '193 parallel load, and this measures it directly.
#
# The two HALTs at 0x0006/0x0007 are a FALL-THROUGH TRAP: a JMP that fails to
# load PC at all runs into them and leaves OB at the poison, which must not be
# confusable with landing on a pad. They also align the grid to 0x0008.
PAD_BASE = 0x0008               # first pad; the header above is exactly 8 bytes
PAD_TOP = 0x0100                # one page of pads is plenty
PAD_TARGET = 0x0040             # distinctive, 4-aligned, mid-grid


def _pads():
    """LDAI n; OUT; HALT at every 4-byte slot — exactly 4 bytes each."""
    out = []
    for a in range(PAD_BASE, PAD_TOP, 4):
        if a == PAD_TARGET:
            out.append("padtarget")
        out += [("LDAI", a & 0xFF), ("OUT",), ("HALT",)]
    return out


PADS_PROGRAM = [
    ("LDAI", POISON), ("OUT",),         # 0x0000-0x0002
    ("JMP", Ref("padtarget")),          # 0x0003-0x0005
    ("HALT",), ("HALT",),               # 0x0006-0x0007  fall-through trap
] + _pads()

# probe — THE SMALLEST QUESTION WORTH ASKING. LDAI then OUT, no ALU at all:
# does an immediate byte reach A and come back out on OB? That splits the
# milestone in half. If OB shows the constant, the load/store/OUT path is
# proven and any wrong sum is the ALU's; if it does not, the fault is upstream
# of the ALU and no amount of staring at a sum will find it. 0x39 is
# non-palindromic (reverses to 0x9C), so a flipped bank self-names.
PROBE_VALUE = 0x39

PROBE_PROGRAM = [
    ("LDAI", PROBE_VALUE),
    ("OUT",),
    ("HALT",),
]

# adda / addb — ISOLATE THE TWO ALU OPERANDS. Adding a known value to ZERO
# means the answer IS the operand, so each image asks about one shadow latch on
# its own. A sum cannot distinguish a bad TMP_A from a bad TMP_B from a bad
# result path; these can. Both expect the SAME witness, so the pair reads as a
# two-bit answer.
ADDA_PROGRAM = [                     # A carries the value, B is zero
    ("LDAI", PROBE_VALUE), ("LDBI", 0x00), ("ADD",), ("OUT",), ("HALT",),
]
ADDB_PROGRAM = [                     # B carries the value, A is zero
    ("LDAI", 0x00), ("LDBI", PROBE_VALUE), ("ADD",), ("OUT",), ("HALT",),
]

# in — THE INTERACTIVE ONE. The second addend comes off SW1 instead of the
# ROM, so the machine takes an operand from the bench. A is the same 0x2F the
# milestone uses, so with the switches set to 0x1E the answer is the SAME 0x4D
# — the value blocks 4 and 5 already proved. Only its SOURCE changed, which
# makes a wrong answer point squarely at the '244 -> W path.
#
# SW1 IS ACTIVE LOW: R17-R24 pull IS0-7 to +5V and the switch pulls down, so
# the byte the '244 puts on W has a 0 wherever a switch is CLOSED. To present
# 0x1E = 0b00011110, CLOSE the switches for bits 0, 5, 6 and 7.
IN_SW = ADDEND_B                        # 0x1E, presented on SW1

IN_PROGRAM = [
    ("LDAI", POISON), ("OUT",),         # destroy the previous answer first
    ("LDAI", ADDEND_A),                 # A = 0x2F, from ROM
    ("IN",),                            # B <- SW1, and TMP_B with it
    ("ADD",), ("OUT",), ("HALT",),
]

# ---- cylon — THE VICTORY LAP -------------------------------------------
# Not a coverage image and deliberately NOT in COVERAGE: it never halts and
# has no final answer, so there is nothing for the block ladder to assert. It
# exists to be LOOKED AT. Burned 2026-08-04, the day the whole ISA first ran.
#
# WHY IT IS UNROLLED, and what that says about the ISA:
#
#   1. B IS IMMEDIATE-ONLY. There is no LDB-from-memory and no MOV, so TMP_B
#      can only ever hold a constant. `ADD` computes TMP_A + TMP_B, so the
#      shift-left trick A+A is IMPOSSIBLE at runtime — the pattern cannot be
#      computed, it has to be tabulated.
#   2. THERE IS NO CALL/RET. The delay cannot be a subroutine, so every frame
#      carries its own inlined copy. That is 34 bytes x 14 frames.
#   3. THERE IS NO INDEXED ADDRESSING. The table cannot be walked with a
#      pointer, so each frame is its own LDAI/OUT pair.
#
# Every one of those three is a step on the growth plan (shifter, stack,
# D:E index pair). This program is what the machine looks like without them,
# and it is worth keeping as the before-picture.
#
# TIMING at 1.024MHz (T = 976.6ns):
#   inner iteration  LDA 4T + LDBI 2T + SUB 2T + STA 4T + JNZ 4T = 16T = 15.6us
#   inner x 255                                             = 3.98ms
#   outer iteration  = setup 6T + 4080T + 16T = 4102T       = 4.01ms
#   outer x 25                                              = ~100ms per frame
#   14 frames                                               = ~1.4s per sweep
CYLON_INNER = RAM_BASE + 0x10       # clear of every coverage image's scratch
CYLON_OUTER = RAM_BASE + 0x11
CYLON_OUTER_N = 25                  # ~100ms per frame; raise to slow the sweep

# One dot, out and back, no repeat at the ends — the eye never stalls.
CYLON_FRAMES = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,
                0x40, 0x20, 0x10, 0x08, 0x04, 0x02]


def _cylon_delay(tag):
    """Nested count-down delay, inlined. Labels are per-frame because there
    is no CALL/RET to share one copy with."""
    return [
        ("LDAI", CYLON_OUTER_N), ("STA", *_addr(CYLON_OUTER)),
        f"{tag}_outer",
        ("LDAI", 0xFF), ("STA", *_addr(CYLON_INNER)),
        f"{tag}_inner",
        ("LDA", *_addr(CYLON_INNER)), ("LDBI", 0x01), ("SUB",),
        ("STA", *_addr(CYLON_INNER)),
        ("JNZ", Ref(f"{tag}_inner")),
        ("LDA", *_addr(CYLON_OUTER)), ("LDBI", 0x01), ("SUB",),
        ("STA", *_addr(CYLON_OUTER)),
        ("JNZ", Ref(f"{tag}_outer")),
    ]


def _build_cylon():
    prog = ["sweep"]
    for i, frame in enumerate(CYLON_FRAMES):
        prog += [("LDAI", frame), ("OUT",)] + _cylon_delay(f"f{i}")
    prog += [("JMP", Ref("sweep"))]        # forever. No HALT anywhere.
    return prog


CYLON_PROGRAM = _build_cylon()

# images whose answer depends on the switches. Everything else is read with
# the default, and the rig is told the setting rather than left to guess.
COVERAGE_SW = {"in": IN_SW}

COVERAGE = {
    "probe": PROBE_PROGRAM,
    "adda": ADDA_PROGRAM,
    "addb": ADDB_PROGRAM,
    "real": PROGRAM,
    "in": IN_PROGRAM,
    "alu": ALU_PROGRAM,
    "mem": MEM_PROGRAM,
    "flow": FLOW_PROGRAM,
    "loop": LOOP_PROGRAM,
    "mardisc": MARDISC_PROGRAM,
    "pads": PADS_PROGRAM,
    "stack": STACK_PROGRAM,
}


def build_image(program):
    code = assemble(program)
    if len(code) > SIZE:
        raise BuildError("program larger than the ROM")
    if code[0] == DIAG_ZERO:
        raise BuildError("program byte 0 collides with the diag signature")
    return code + bytes([SAFE_FILL]) * (SIZE - len(code))


def build_real():
    code = assemble(PROGRAM)
    if len(code) > SIZE:
        raise BuildError("program larger than the ROM")
    if code[0] == DIAG_ZERO:
        raise BuildError("program byte 0 collides with the diag signature")
    return code + bytes([SAFE_FILL]) * (SIZE - len(code))


def diag_triple_max():
    """Worst-case ambiguity of three CONSECUTIVE diag bytes: how many addresses
    can share one triple. block2.fetch proves the fetch path reads ROM at PC,
    PC+1, PC+2 by matching such a triple, so this is the threshold below which
    a match is meaningful — and it is STRUCTURAL, not luck. diag_byte truncates
    to 8 bits, so three bytes constrain 24 bits with enough structure left to
    leave a 4-fold ambiguity almost everywhere and 8-fold in places. A
    hand-picked threshold of 4 would have false-failed on 3% of positions."""
    seen = {}
    for a in range(SIZE - 2):
        k = (diag_byte(a), diag_byte(a + 1), diag_byte(a + 2))
        seen[k] = seen.get(k, 0) + 1
    return max(seen.values())


# ---- CRC-16/CCITT-FALSE (same routine the rig links, src/crc16.c) ------
def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 \
                else (crc << 1) & 0xFFFF
    return crc


# ---- rig expect header --------------------------------------------------
def emit_header(real, crcs, path, cov=None):
    code_len = len(assemble(PROGRAM))
    lines = [
        "/* GENERATED by docs/notes/progrom_gen.py — do not edit.",
        "   Regenerate: python3 docs/notes/progrom_gen.py */",
        "#ifndef PROGROM_EXPECT_H",
        "#define PROGROM_EXPECT_H",
        "#ifdef __AVR__",
        "#include <avr/pgmspace.h>",
        "#else",
        "#define PROGMEM",
        "#endif",
        "#include <stdint.h>",
        "",
        f"#define PR_SIZE {SIZE}u",
        f"#define PR_SAFE_FILL 0x{SAFE_FILL:02X}u",
        "",
        "/* burn signatures: byte 0 of each image */",
        f"#define PR_DIAG_BYTE0 0x{build_diag()[0]:02X}u",
        f"#define PR_REAL_BYTE0 0x{real[0]:02X}u",
        "",
        "/* CRC-16/CCITT-FALSE over all 32768 bytes */",
    ]
    for name, val in crcs.items():
        lines.append(f"#define {name} 0x{val:04X}u")
    lines += [
        "",
        f"#define PR_DIAG_ZERO 0x{DIAG_ZERO:02X}u",
        f"#define PR_DIAG_WALK 0x{DIAG_WALK:02X}u",
        "",
        "/* diag value is a pure function of its address — the rig computes",
        "   it rather than carrying a 32KB table. Self-naming on 0 and 2^k. */",
        "static inline uint8_t pr_diag_byte(uint16_t a) {",
        "    a &= (uint16_t)(PR_SIZE - 1u);",
        "    if (a == 0u) return PR_DIAG_ZERO;",
        "    if ((a & (uint16_t)(a - 1u)) == 0u) {",
        "        uint8_t k = 0;",
        "        while ((uint16_t)(a >> k) > 1u) k++;",
        "        return (uint8_t)(PR_DIAG_WALK | k);",
        "    }",
        "    return (uint8_t)(((uint16_t)(a * 0x9Du)) ^ (a >> 5));",
        "}",
        "",
        "/* the shipped program; every address at or past PR_PROGRAM_LEN",
        "   reads PR_SAFE_FILL */",
        f"#define PR_PROGRAM_LEN {code_len}u",
        "static const uint8_t PR_PROGRAM[PR_PROGRAM_LEN] PROGMEM = {",
        "    " + ", ".join(f"0x{b:02X}" for b in real[:code_len]) + ",",
        "};",
        "",
        f"#define PR_EXPECT_SUM 0x{EXPECT_SUM:02X}u   /* the milestone result */",
        f"#define PR_POISON 0x{POISON:02X}u"
        f"   /* OB is set to this BEFORE the sum is computed */",
        f"#define PR_EXPECT_ENDS {simulate(PROGRAM)['ends']}u"
        f"   /* one END per instruction retired */",
        "",
        "#endif",
        "",
    ]
    lines += ["",
              "/* Worst-case ambiguity of three CONSECUTIVE diag bytes: the most",
              "   addresses that can share one triple. block2.fetch matches such a",
              "   triple to prove the fetch reads ROM at PC, PC+1, PC+2, so a match",
              "   count at or below this is meaningful and anything above it is not.",
              "   STRUCTURAL, not luck — generated, never hand-picked. */",
              f"#define PR_DIAG_TRIPLE_MAX {diag_triple_max()}u"]
    if cov:
        lines += ["", "/* progressive ISA-coverage images. Each ends OUT; HALT",
                  "   because OB is the only datapath observable on the block",
                  "   ladder. Burn as needed; PROG.bin (the milestone) is never",
                  "   regenerated under another name. */",
                  f"#define PR_COV_COUNT {len(cov)}u",
                  "typedef struct { const char *name; uint16_t crc;",
                  "                 uint8_t expect_ob; uint8_t expect_ends;",
                  "                 uint8_t sw; uint8_t needs_sw; } prcov_t;",
                  "static const prcov_t PR_COVERAGE[PR_COV_COUNT] = {"]
        for tag, (crc, ob, ends, sw, needs) in cov.items():
            lines.append(f'    {{"{tag}", 0x{crc:04X}u, 0x{ob:02X}u, {ends}u, '
                         f'0x{sw:02X}u, {1 if needs else 0}u}},')
        lines.append("};")
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ---- --expected: the bring-up sheet's own generator --------------------
# fpga/BRINGUP_FPGA.md and tests/dino_bringup/BRINGUP.md both need "what
# should OB/the LEDs show for image X" tables. Retyping simulate()'s
# output into a doc is exactly the class of drift CLAUDE.md's "everything
# generated, nothing retyped" rule exists to prevent -- this prints the
# SAME (crc, out, ends, sw, needs_sw) tuple main()'s own cov dict below
# computes, side-effect-free (no roms/*.bin writes, no header emit), so a
# doc author (or a doc-freshness check) can run it standalone at any
# time. "real" is included even though it is not in COVERAGE's loop body
# below (main() special-cases it because PROG.bin's write path differs,
# not because its expected OB is any less real).
def expected_rows():
    """[(tag, ob, ends, sw, needs_sw), ...] for every progrom_gen.COVERAGE
    tag, in COVERAGE's own iteration order. ob is None if the interpreter
    never reached HALT for that tag (would indicate a broken image, not a
    normal case -- every current COVERAGE program ends OUT; HALT)."""
    rows = []
    for tag, prog in COVERAGE.items():
        sw = COVERAGE_SW.get(tag, 0x00)
        r = simulate(prog, switches=sw)
        rows.append((tag, r["out"] if r["halted"] else None, r["ends"],
                     sw, tag in COVERAGE_SW))
    return rows


def print_expected():
    print("# generated by: python3 docs/notes/progrom_gen.py --expected")
    print("# tag         OB      ends  switches")
    for tag, ob, ends, sw, needs in expected_rows():
        ob_s = f"0x{ob:02X}" if ob is not None else "NEVER-HALTS"
        sw_s = f"0x{sw:02X}" if needs else "-"
        print(f"{tag:<12s} {ob_s:<11s} {ends:<5d} {sw_s}")


def main():
    if "--expected" in sys.argv[1:]:
        print_expected()
        return 0
    real, diag = build_real(), build_diag()
    os.makedirs(ROMS, exist_ok=True)
    crcs = {}
    for tag, img, fn in (("REAL", real, "PROG.bin"),
                         ("DIAG", diag, "PROG_diag.bin")):
        with open(os.path.join(ROMS, fn), "wb") as f:
            f.write(img)
        crcs[f"PR_CRC_{tag}"] = crc16(img)
    # progressive ISA-coverage images. "real" is already written above as
    # PROG.bin — the milestone image is never regenerated under another name,
    # because block 6 must accept on exactly the image it was specified
    # against.
    cov = {}
    for tag, prog in COVERAGE.items():
        if tag == "real":
            continue
        img = build_image(prog)
        with open(os.path.join(ROMS, f"PROG_{tag}.bin"), "wb") as f:
            f.write(img)
        r = simulate(prog, switches=COVERAGE_SW.get(tag, 0x00))
        cov[tag] = (crc16(img), r["out"], r["ends"],
                    COVERAGE_SW.get(tag, 0x00), tag in COVERAGE_SW)
    # cylon is written but NOT registered in PR_COVERAGE: it never halts, so
    # it has no (OB, END) fingerprint for block4.stepped to match. Burning it
    # and running block4.stepped will correctly report "no known image".
    cyl = build_image(CYLON_PROGRAM)
    with open(os.path.join(ROMS, "PROG_cylon.bin"), "wb") as f:
        f.write(cyl)
    cyl_crc = crc16(cyl)
    cyl_len = len(assemble(CYLON_PROGRAM))
    emit_header(real, crcs, HDR, cov)
    print(f"wrote {3 + len(cov)}x {SIZE}B bins -> {ROMS}")
    print(f"wrote expect header -> {HDR}")
    print("burn order: DIAG first (rom.order proves 15 address lines),")
    print("            then REAL (the milestone program)")
    print("  coverage images (burn as needed; each ends OUT; HALT):")
    for tag, (crc, ob, ends, sw, needs) in cov.items():
        extra = f"  SW1=0x{sw:02X}" if needs else ""
        print(f"    PROG_{tag}.bin  crc=0x{crc:04X}  OB 0x{ob:02X}  "
              f"{ends} END pulses{extra}")
    print(f"    PROG_cylon.bin  crc=0x{cyl_crc:04X}  {cyl_len} bytes  "
          f"NEVER HALTS — {len(CYLON_FRAMES)} frames, ~"
          f"{CYLON_OUTER_N * 4.006:.0f}ms each, ~"
          f"{len(CYLON_FRAMES) * CYLON_OUTER_N * 4.006 / 1000:.1f}s per sweep")
    print(f"  program: {' '.join(s[0] for s in PROGRAM)}"
          f"  -> OUT should show 0x{EXPECT_SUM:02X}")
    for name, val in crcs.items():
        print(f"  {name} = 0x{val:04X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
