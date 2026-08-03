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

RAM_BASE = 0x8000       # M15 selects: ROM 0x0000-0x7FFF, RAM 0x8000-0xFFFF


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
            dst, src = _DST[w & 7], _SRC[(w >> 3) & 7]
                # CW9..CW11 hold the '382 code BIT-REVERSED — CW9 is labelled SA2
            # and wired to the chip's select MSB. _sa_bits is its own inverse,
            # so the same call unpacks it. Reading the field raw here would
            # make the interpreter compute AND where the hardware computes ADD,
            # which is the very fault this encoding change fixes.
            misc = _MISC[(w >> 6) & 7]
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

COVERAGE = {
    "probe": PROBE_PROGRAM,
    "adda": ADDA_PROGRAM,
    "addb": ADDB_PROGRAM,
    "real": PROGRAM,
    "alu": ALU_PROGRAM,
    "mem": MEM_PROGRAM,
    "flow": FLOW_PROGRAM,
    "loop": LOOP_PROGRAM,
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
                  "                 uint8_t expect_ob; uint8_t expect_ends; } prcov_t;",
                  "static const prcov_t PR_COVERAGE[PR_COV_COUNT] = {"]
        for tag, (crc, ob, ends) in cov.items():
            lines.append(f'    {{"{tag}", 0x{crc:04X}u, 0x{ob:02X}u, {ends}u}},')
        lines.append("};")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
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
        r = simulate(prog)
        cov[tag] = (crc16(img), r["out"], r["ends"])
    emit_header(real, crcs, HDR, cov)
    print(f"wrote {2 + len(cov)}x {SIZE}B bins -> {ROMS}")
    print(f"wrote expect header -> {HDR}")
    print("burn order: DIAG first (rom.order proves 15 address lines),")
    print("            then REAL (the milestone program)")
    print("  coverage images (burn as needed; each ends OUT; HALT):")
    for tag, (crc, ob, ends) in cov.items():
        print(f"    PROG_{tag}.bin  crc=0x{crc:04X}  OB 0x{ob:02X}  {ends} END pulses")
    print(f"  program: {' '.join(s[0] for s in PROGRAM)}"
          f"  -> OUT should show 0x{EXPECT_SUM:02X}")
    for name, val in crcs.items():
        print(f"  {name} = 0x{val:04X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
