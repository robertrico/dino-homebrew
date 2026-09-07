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

ROM_IMAGE  = 32768      # the AT28C256 itself: pad length, CRC domain, PR_SIZE
ROM_WINDOW = 16384      # addresses that decode to U24 after phase E
IO_BASE    = 0x4000     # ROM_WINDOW .. RAM_BASE is the I/O window
SAFE_FILL = OPCODES["HALT"]     # erased/overrun ROM must HALT, never rave

# ---- diag image ---------------------------------------------------------
DIAG_ZERO = 0xA5                # address 0 marker (also the burn signature)
DIAG_WALK = 0x40                # 2^k -> DIAG_WALK|k, k = 0..14
WITNESS_ADDRS = [0] + [1 << k for k in range(15)]


def diag_byte(addr):
    """Content-addressed diag value. Self-naming on the witness set."""
    addr &= ROM_IMAGE - 1
    if addr == 0:
        return DIAG_ZERO
    if addr & (addr - 1) == 0:                  # exact power of two
        return DIAG_WALK | addr.bit_length() - 1
    return ((addr * 0x9D) ^ (addr >> 5)) & 0xFF


def build_diag():
    return bytes(diag_byte(a) for a in range(ROM_IMAGE))


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


class Unoracled(BuildError):
    """The oracle DECLINES to answer, by design -- PHASE_G.md SECTION 5.
    The program is legal and the image is buildable; there is no number
    to compare OB against. asm.py --run reports it and still writes.
    Every other BuildError is a fault and stays fatal."""


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
from microcode_gen import (SRC_BANK_N, DST_BANK_N, MISC_BANK_N,  # noqa: E402
                           MUX_PC)

RAM_BASE = 0x8000       # ROM 0x0000-0x3FFF, I/O 0x4000-0x7FFF, RAM 0x8000+

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


# The '382's CN+4 is only meaningful for the three ARITHMETIC function codes.
# BSUB=1, SUB=2, ADD=3; CLR=0, XOR=4, OR=5, AND=6, SET=7 are logic modes and
# the datasheet does not define CN+4 for them.
#
# THIS IS WHY _alu_op RETURNS A DEFINEDNESS FLAG rather than a plain 0. An
# oracle that answered "carry is 0 after AND" would be a STAND-IN BETTER THAN
# THE HARDWARE -- the defect class that let a rig-emulated bridge pass
# schematic bug 4, and the same reason the '169 model powers SP up non-zero.
# simulate() refuses a JNC that reads an undefined carry instead of guessing.
_CARRY_DEFINED = ("ADD", "SUB", "BSUB")


def _alu_op(op, a, b):
    """(result, carry, carry_is_defined).

    CARRY IS NOT BORROW. ALU_CIN = NAND(SA1, SA0), so SUB (0b010) and BSUB
    (0b001) both get CIN=1 and the '382 computes A + ~B + 1. CN+4 is then a
    NOT-borrow: FLAG_C = 1 means A >= B unsigned, FLAG_C = 0 means A < B.
    That polarity is what makes JNC an unsigned "less than", and inverting it
    here would make every JNC branch the wrong way while every existing
    JNZ image still passed."""
    if op == "CLR":
        return 0, 0, False
    if op == "SET":
        return 0xFF, 0, False
    if op == "ADD":
        r = a + b
        return r & 0xFF, (r >> 8) & 1, True
    if op == "SUB":
        return (a - b) & 0xFF, 1 if a >= b else 0, True
    if op == "BSUB":
        return (b - a) & 0xFF, 1 if b >= a else 0, True
    if op == "XOR":
        return a ^ b, 0, False
    if op == "OR":
        return a | b, 0, False
    if op == "AND":
        return a & b, 0, False
    raise BuildError(f"interpreter has no model for SA={op}")


IO_PARK = OPCODES["HALT"]       # 0xFF. W's bus-park pullups, and HALT, and
                                # SAFE_FILL are the same byte on purpose: an
                                # unclaimed address stops the machine.


# ---- card zero: the DIP switch ------------------------------------------
# The '138 on the card decodes M11-M13 -- the SLOT NUMBER -- so each card
# owns 2K dedicated and NOTHING MIRRORS. 8 slots x 2K = the whole 16K
# window. Card zero holds slot 0, 0x4000-0x47FF, and ignores M0-M10
# entirely: it is a bare '244, not a register file, so it answers at all
# 2048 addresses in its slot and at none outside it.
DIP_BASE = IO_BASE + 0x0000     # '138 output O0 -- slot 0
DIP_SLOT = 0x7FF                # 2K of low bits the card does not decode


# ---- card one: the serial card (PHASE G) --------------------------------
# U101 O1 -- slot 1, 0x4800-0x4FFF. A0-A2 come off M0-M2, so the eight
# 16550 registers sit at base+0..7 and, M3-M10 being undecoded, repeat every
# 8 bytes through the whole slot (PHASE_G.md GOTCHA 3). Nothing outside the
# slot answers.
#
# THE ORACLE MODELS EXACTLY ONE BYTE OF THIS CARD, and that is a ruling, not
# an omission (PHASE_G.md SECTION 5). The scratch register at base+7 is
# inert -- datasheet 8.10, "does not control the UART in anyway" -- so it is
# one byte of state with no clock behind it. THR, RBR, the FIFOs, the baud
# generator and loopback are TEMPORAL: THRE and DR move on bit boundaries,
# and simulate() interprets microcode rows and has no notion of a bit time.
# A model of those would be a second UART written by the same hand as the
# spec, agreeing with itself while both were wrong. So every other register
# RAISES. The images that touch them are generated and burnable, and their
# expected bytes are DATASHEET-SOURCED, UNORACLED -- say so every time.
SER_BASE = IO_BASE + 0x0800     # '138 output O1 -- slot 1
SER_SLOT = 0x7FF
SER_REG  = 0x7                  # A0-A2 <- M0-M2; the rest of the slot mirrors
SER_RBR = SER_THR = SER_DLL = SER_BASE + 0   # DLAB banks 0 and 1
SER_IER = SER_DLM = SER_BASE + 1
SER_IIR = SER_FCR = SER_BASE + 2
SER_LCR = SER_BASE + 3
SER_MCR = SER_BASE + 4
SER_LSR = SER_BASE + 5
SER_MSR = SER_BASE + 6
SER_SCR = SER_BASE + 7
_SER_REG_NAME = {0: "RBR/THR/DLL", 1: "IER/DLM", 2: "IIR/FCR", 3: "LCR",
                 4: "MCR", 5: "LSR", 6: "MSR", 7: "SCR"}


def uart_reset():
    """The card's state after Master Reset. FACT, datasheet section 6.0,
    MR: "clears all the registers (except the Receiver Buffer, Transmitter
    Holding, and Divisor Latches)". SCR is none of the three."""
    return {"scr": 0x00}


def _ser_reg(addr, uart, verb):
    reg = addr & SER_REG
    if reg != SER_REG:
        raise Unoracled(
            f"{verb} of UART register {_SER_REG_NAME[reg]} at 0x{addr:04X}: "
            f"the oracle models ONLY the scratch register (base+7). The rest "
            f"are temporal and have no answer key -- PHASE_G.md SECTION 5. "
            f"This image is DATASHEET-SOURCED, UNORACLED; do not expect a "
            f"number from simulate().")
    return uart


# ---- the scripted serial stimulus: A TEST DOUBLE, NOT A UART MODEL -------
# PHASE_G.md SECTION 5 forbids modelling THR/RBR/the FIFOs because they are
# TEMPORAL and this interpreter has no clock. simulate(serial_in=...) does
# not model time and does not pretend to:
#
#     DR   (LSR bit 0)   "bytes remain in the script"
#     THRE (LSR bit 5)   always set -- kinder than the hardware, and the
#                        reason this must never be read as a UART model
#     RBR read           pops the script; empty is a FAULT, not a 0
#     THR write          appended to `tx`
#     DLAB               tracked, so the divisor dance is not "transmitted"
#
# It exists so a program's PARSING and FORMATTING can be host-tested (the
# monitor). The polling idiom itself is bench-proven by PROG_serrx. Without
# serial_in nothing here runs and LSR/RBR/THR stay Unoracled.
#
# IDLE: with the script exhausted, a third consecutive LSR read with no THR
# write or RBR read between them is a program spinning on DR, and the run
# stops there with st["idle"] = True. A THRE poll never reads LSR twice in
# a row (THRE is always set), so a transmit-only program runs to its HALT.
IDLE_LSR_READS = 3


def _serial_result(st, uart):
    """Fold the scripted session's observables into simulate()'s result."""
    if uart is not None and "rx" in uart:
        st["tx"] = bytes(uart["tx"])
        st["idle"] = bool(uart.get("idle"))
    return st


def uart_script(data):
    """Card state for a scripted session: `data` is what the host types."""
    from collections import deque
    return {"scr": 0x00, "rx": deque(bytes(data)), "tx": bytearray(),
            "lcr": 0x00, "regs": {}, "lsr_run": 0}


def _ser_read(addr, uart):
    if "rx" not in uart:
        return _ser_reg(addr, uart, "read")["scr"]
    reg = addr & SER_REG
    if reg == 5:                                  # LSR: DR | THRE | TEMT
        if uart["rx"]:
            uart["lsr_run"] = 0
            return 0x61
        uart["lsr_run"] += 1
        if uart["lsr_run"] >= IDLE_LSR_READS:
            uart["idle"] = True                   # simulate() stops here
        return 0x60
    if reg == 0:
        if uart["lcr"] & 0x80:                    # DLAB: it is DLL
            return uart["regs"].get("dll", 0)
        if not uart["rx"]:
            raise BuildError(
                f"RBR read at 0x{addr:04X} with nothing waiting: the program "
                f"read the FIFO without polling DR (LSR bit 0)")
        uart["lsr_run"] = 0
        return uart["rx"].popleft()
    if reg == 7:
        return uart["scr"]
    return _ser_reg(addr, uart, "read")          # IER/IIR/LCR/MCR/MSR: no key


def _ser_write(addr, val, uart):
    val &= 0xFF
    if "rx" not in uart:
        _ser_reg(addr, uart, "write")["scr"] = val
        return
    reg = addr & SER_REG
    dlab = uart["lcr"] & 0x80
    if reg == 0:
        if dlab:
            uart["regs"]["dll"] = val
        else:
            uart["tx"].append(val)
            uart["lsr_run"] = 0
    elif reg == 1:
        uart["regs"]["dlm" if dlab else "ier"] = val
    elif reg == 3:
        uart["lcr"] = val
    elif reg == 7:
        uart["scr"] = val
    else:
        uart["regs"][_SER_REG_NAME[reg]] = val    # FCR / MCR: accepted, inert


def io_read(addr, switches, uart=None):
    """One byte from the I/O window, 0x4000-0x7FFF.

    `uart` is the serial card's state from uart_reset(); None means no card
    in slot 1 -- the phase-E machine -- and the slot reads the park."""
    if (addr & ~DIP_SLOT) == DIP_BASE:
        return switches & 0xFF
    if (addr & ~SER_SLOT) == SER_BASE and uart is not None:
        return _ser_read(addr, uart)
    return IO_PARK


def io_write(addr, val, uart):
    """A write into the I/O window. True if something took it. Card zero is
    a bare '244 and takes nothing; the serial card is the first consumer of
    ~{IO_WR} in this machine's life."""
    if (addr & ~SER_SLOT) == SER_BASE and uart is not None:
        _ser_write(addr, val, uart)
        return True
    return False


def simulate(program, max_steps=100000, switches=0x00,
             image=None, rom_window=None, serial=True, serial_in=None):
    """Execute an assembled image by interpreting its microcode rows.

    `serial=False` pulls the serial card out of slot 1 -- the phase-E
    machine. PROG_window's AFTER reading depends on it: a PC that crosses
    0x4000 NOP-slides through card zero and, with the card fitted, fetches
    UART registers as opcodes at 0x4800 (PHASE_G.md GOTCHA 2), which is
    undefined. With the slot empty it finds the park and halts.

    `serial_in=b"..."` is what the host types, and turns on the scripted
    serial stimulus (see uart_script -- a test double, not a UART model).
    The result then carries `tx`, the bytes the program wrote to THR, and
    `idle`, True when the run stopped because the program was polling DR
    with the script exhausted.

    Returns a dict of observables. `out` is what OB would read — the only
    datapath observable the block ladder has, which is why every coverage
    image ends OUT; HALT."""
    code = assemble(program) if image is None else image
    poison = {i for i, _ in _poison_spans(program)} if program else set()
    window = ROM_WINDOW if rom_window is None else rom_window
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
    if serial_in is not None:
        uart = uart_script(serial_in)         # the scripted session
    else:
        uart = uart_reset() if serial else None   # slot 1 after MR, or empty
    # THE FLAG MODEL. U49 is a '273 with NO clock enable -- it re-clocks every
    # T-state -- and U48 is a '157 whose select is ~{ALU_OUT}. So the flags
    # UPDATE on any row that sources the ALU and HOLD on every other row.
    # That hold is what makes compare-then-branch work: the FETCH, the
    # immediate loads and the operand states between a CMP and its branch
    # never assert ~{ALU_OUT}.
    #
    # flag_c_defined tracks whether the LAST ALU op was one of the three
    # arithmetic function codes -- see _CARRY_DEFINED. It is not hardware;
    # it is the oracle refusing to invent an answer the '382 does not give.
    flag_z = 0
    flag_c = 0
    flag_c_defined = False
    # `outs` is the ORDERED history of what OB showed, not just the last
    # value. A never-halting image has no final answer, so the only way to
    # assert one is to compare the SEQUENCE -- which is exactly what a
    # stack-driven display makes meaningful.
    st = {"ram_writes": 0, "ram_reads": 0, "branches_taken": 0,
          "branches_not_taken": 0, "hit_poison": False, "stored": None,
          "steps": 0, "ends": 0, "outs": []}

    def rd(a):
        if a < window:
            return code[a] if a < len(code) else SAFE_FILL
        if a < RAM_BASE:
            return io_read(a, switches, uart)
        return ram.get(a, 0)

    while st["steps"] < max_steps:
        if uart is not None and uart.get("idle"):
            break                               # script done, program on DR
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

            # M carries the PC when CW14 is set and MAR otherwise. One bus,
            # one address, and every memory access in this state uses it.
            def _addr_bus():
                return pc if (w & MUX_PC) else mar

            val = None
            if src == "ROM":
                val = rd(pc)
            elif src == "RAM":
                val = rd(_addr_bus())
                st["ram_reads"] += 1
            elif src == "REG_A":
                val = A
            elif src == "REG_B":
                val = B
            elif src == "REG_C":
                val = C
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
                val, flag_c, flag_c_defined = _alu_op(sa, tmp_a, tmp_b)
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
                # THE ADDRESS COMES OFF THE BUS, NOT FROM MAR DIRECTLY. There
                # is one address bus and CW14 chooses what drives it, so a row
                # that sets mux_pc writes at the PC no matter what MAR holds.
                #
                # Modelling this as `ram[mar]` was KINDER THAN THE HARDWARE
                # and it hid a real defect: MVI/MVIX/MVIS were encoded
                # src=ROM dst=RAM, which cannot work, and the oracle reported
                # them working. check_word refuses those rows now, but the
                # oracle must not be the thing that would have missed it.
                a = _addr_bus()
                if a >= RAM_BASE:
                    ram[a] = val
                elif not (a >= IO_BASE and io_write(a, val, uart)):
                    st["lost_writes"] = st.get("lost_writes", 0) + 1
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
                # COND_TAKEN = NOR(~{COND}, COND_FLAG): taken when the
                # SELECTED flag is ZERO. The machine has exactly ONE branch
                # polarity; U77 changes which flag, never the sense.
                #
                # U77 IS A 2:1 ON CW21 ALONE. CW22 is a no-connect, so this
                # reads bit 21 and ignores bit 22 exactly as the copper does
                # -- modelling a 4:1 here would pass encodings the hardware
                # cannot honour. word() refuses V and N for the same reason.
                if (w >> 21) & 1:
                    flag = flag_z                   # S=1 -> I1 = FLAG_Z
                else:
                    # S=0 -> I0 = FLAG_C. A carry no arithmetic op defined is
                    # not 0, it is unknown: the '382 does not specify CN+4 for
                    # its logic function codes. Refuse rather than guess.
                    if not flag_c_defined:
                        raise Unoracled(
                            f"pc=0x{pc:04X}: JNC reads a carry that no "
                            f"arithmetic op defined -- the last ALU row was a "
                            f"LOGIC function code and the '382 does not "
                            f"specify CN+4 for those. Put an ADD/SUB/BSUB "
                            f"(or CMP/CMPB) before the branch.")
                    flag = flag_c
                if not flag:
                    pc = mar
                    st["branches_taken"] += 1
                else:
                    st["branches_not_taken"] += 1
            elif misc == "REG_OUT_LOAD":
                # OB LATCHES THE BUS, NOT THE ACCUMULATOR. NETLIST-EXTRACTED
                # 2026-08-27, registers_a_b.kicad_sch:
                #     U44  '245  A side = MDR0-7,  ~CE = ~{REG_OUT_LOAD}
                #               DIR tied +5V,  B side -> U35.D0-7
                #     U35  '373  LE = ~{REG_OUT_LE}  (U57.13)
                # so whatever is on MDR when the strobe fires is what OB
                # shows. `src=REG_A` was a MICROCODE CONVENTION and never a
                # wire, which is why OUT-from-anything costs no hardware.
                #
                # Modelling this as `out = A` was correct for exactly one
                # instruction and silently wrong for the sixteen that came
                # with phase F+.
                #
                # val is None only if no source drove the bus at all; then
                # U25 is off and U44 passes whatever MDR is holding.
                shown = val if val is not None else mdr
                out = shown
                st["outs"].append(shown)
            elif misc == "SP_UP":
                sp = (sp + 1) & 0xFFFF
            elif misc == "SP_DOWN":
                sp = (sp - 1) & 0xFFFF

            if halt:
                st.update(out=out, halted=True, A=A, B=B, C=C,
                          flag_z=flag_z, flag_c=flag_c,
                          flag_c_defined=flag_c_defined, sp=sp)
                return _serial_result(st, uart)
            if (w >> 12) & 1:                       # END
                st["ends"] += 1
                break
    st.update(out=out, halted=False, A=A, B=B, C=C,
              flag_z=flag_z, flag_c=flag_c,
              flag_c_defined=flag_c_defined, sp=sp)
    return _serial_result(st, uart)


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
    # POISON FIRST. U35 has no reset, so OB holds the PREVIOUS image's
    # answer until something overwrites it -- and the image burned
    # immediately before this one is PROG_sp, which answers 0x27. THE SAME
    # BYTE THIS IMAGE EXPECTS. The return lands exactly on the OUT below, so
    # a RET that lands ONE BYTE LATE hits the HALT instead, OUT never runs,
    # and OB still reads PROG_sp's 0x27 -- a false pass that looks identical
    # to success. Added 2026-08-24; the image ran without it until then.
    ("LDAI", POISON), ("OUT",),
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

# PROG_sp -- the PHASE-B bench gate: the SP + RAM round trip proven by the
# push/pop family ALONE. Same bytes, same swapped-register pops, same answer
# signature as PROG_stack (0x27 correct LIFO, 0xD9 names a wrong order) --
# but no CALL/RET, because the PC-pushback '245s (U72/U73) are phase-C
# hardware that does not exist yet when this image gates the bench. SUB runs
# in the main line rather than inside a subroutine: reaching OUT here proves
# nothing about the PC, and that is the point. PROG_sp passing while
# PROG_stack fails localises the fault to the phase-C copper.
# PROG_sp1 -- ONE push, ONE pop, and nothing else. The rung between
# PROG_probe (no stack at all) and PROG_sp (two pushes, swapped pops, a
# subtract and the ~TC chain). When PROG_sp fails there is no way to tell
# which of those parts broke; this image removes all of them.
#
# It proves exactly four things and deliberately nothing more: SP -> MAR
# through U67/U68, the RAM write at [SP], one SP_DOWN, one SP_UP, and the
# read back. No LIFO ordering -- a single value cannot be out of order --
# and no carry boundary, since SP moves by one from 0x80FF.
#
# 0x2C bit-reverses to 0x34, so a flipped OB ribbon still names itself.
# 0xFF means the read found a bus nobody drove; 0x00 means the pop read a
# cell the push never wrote.
SP1_PROGRAM = [
    ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),
    ("LDAI", STACK_PUSH_A),             # 0x2C
    ("PUSHA",),                         # [0x80FF] = 0x2C, SP -> 0x80FE
    ("POPA",),                          # SP -> 0x80FF, A <- 0x2C
    ("OUT",),
    ("HALT",),
]

SP_PROGRAM = [
    ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),
    ("LDAI", STACK_PUSH_A),
    ("LDBI", STACK_PUSH_B),
    ("PUSHA",),
    ("PUSHB",),
    ("POPA",),                          # LIFO: A <- what B pushed = 0x53
    ("POPB",),                          #       B <- what A pushed = 0x2C
    ("SUB",),                           # A = A - B = 0x27, main line
    ("OUT",),
    ("HALT",),
]

# ---- calladdr — DID *CALL* PUSH THE RIGHT ADDRESS? ---------------------
# Splits phase C in half. PROG_call runs CALL *and* RET, so a failure there
# lights up FIVE pins that have never been asserted in this machine's life
# and names none of them. This image runs CALL and NEVER EXECUTES RET, then
# reads the pushed bytes back out of RAM by ABSOLUTE address.
#
#     CALL side   U70.13 ~PC_LO_OUT, U70.12 ~PC_HI_OUT, U72, U73
#     RET side    U30.12 ~REG_C_LOAD, U29.11 ~MDR_OUT, U28.10 ~REG_C_OUT
#
# calladdr passing and call failing puts the fault squarely on the RET side.
#
# WHAT ADDRESS DOES CALL PUSH? **CALL+1, NOT CALL+3.** The pushes happen at
# T3/T7, BEFORE the operand fetch at T9/T10, so PC has been incremented only
# once -- by the T0 fetch -- and points at the CALL's own first operand byte.
# RET compensates on the way out: T11 PC_LOAD restores CALL+1, then T12 and
# T13 both carry PC_UP and step over the two operand bytes to CALL+3.
#
# THOSE TWO TRAILING PC_UP STATES ARE LOAD-BEARING, NOT PADDING. On an LA a
# correct RET looks WRONG -- it loads a PC pointing into the middle of the
# CALL instruction. Do not "fix" it. Read RET to T13 before judging it.
CALLADDR_OK = 0x5C          # 01011100, mirror 0x3A
CALLADDR_BAD_LO = 0xC1      # the pushed LO byte is wrong -> U72 / ~PC_LO_OUT
CALLADDR_BAD_HI = 0xC2      # the pushed HI byte is wrong -> U73 / ~PC_HI_OUT
CALLADDR_PAD = 0x120        # push the CALL above 0x00FF so PC_HI is non-zero


def _build_calladdr(pad=CALLADDR_PAD):
    """CALL, then read the pushed return address back out of RAM.

    Two passes: the expected bytes depend on where the CALL lands, and
    LDBI is a fixed length regardless of operand, so the layout is
    identical between passes."""
    def body(exp_lo, exp_hi):
        return [
            ("LDAI", POISON), ("OUT",),
            ("JMP", Ref("high")),
        ] + [("HALT",)] * pad + [
            "high",
            ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),
            "call_at",                      # CALL pushes call_at + 1
            ("CALL", Ref("sub")),
            "after_call",                   # execution resumes here AFTER a RET
            # A trap, not filler: if CALL fails to JUMP it falls in here and
            # reports the poison instead of quietly reaching the real body.
            ("LDAI", POISON), ("OUT",), ("HALT",),
            "sub",
            ("LDA", *_addr(STACK_TOP - 1)),         # PC_LO, pushed second
            ("LDBI", exp_lo), ("SUB",),
            ("JNZ", Ref("bad_lo")),
            ("LDA", *_addr(STACK_TOP)),             # PC_HI, pushed first
            ("LDBI", exp_hi), ("SUB",),
            ("JNZ", Ref("bad_hi")),
            ("LDAI", CALLADDR_OK), ("OUT",), ("HALT",),
            "bad_lo", ("LDAI", CALLADDR_BAD_LO), ("OUT",), ("HALT",),
            "bad_hi", ("LDAI", CALLADDR_BAD_HI), ("OUT",), ("HALT",),
        ]

    addr, labels = 0, {}
    for step in body(0x00, 0x00):
        if isinstance(step, str):
            labels[step] = addr
            continue
        addr += INSTRUCTIONS[step[0]][0]
    # CALL+1, not CALL+3 -- the pushes at T3/T7 precede the operand fetch
    pushed = labels["call_at"] + 1
    return body(pushed & 0xFF, pushed >> 8)


CALLADDR_PROGRAM = _build_calladdr()

# ---- callraw — REPORT THE BYTE, DO NOT JUDGE IT ------------------------
# THE IMAGE THAT FOUND PHASE C's FAULT, after calladdr had misattributed it.
#
# calladdr compares the pushed address against an expected value and answers
# 0xC1 / 0xC2. On 2026-08-24 it answered 0xC1 -- "the LO byte is wrong" --
# which pointed at U72 and ~PC_LO_OUT. Both were fine. This image OUTs the
# pushed byte RAW, reported 0x26, and 0x26 was instantly recognisable as the
# low byte of the previous JMP's target: U72/U73 had been landed on U11/U12,
# the PC LOAD path, so they were reading stale PCD instead of live PC.
#
# AN ASSERTION COLLAPSES A NUMBER INTO A VERDICT, AND THE NUMBER WAS THE
# CLUE. Pair every assert-style witness with a raw-report twin when the
# observable is an address, a count or a pointer -- "wrong" is worth far less
# than "wrong by how much, and equal to what".
CALLRAW_PAD = 0x120


def _build_callraw(pad=CALLRAW_PAD):
    """CALL, then OUT the pushed PC_LO byte exactly as it landed in RAM."""
    return [
        ("LDAI", POISON), ("OUT",),
        ("JMP", Ref("high")),
    ] + [("HALT",)] * pad + [
        "high",
        ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),
        "call_at",
        ("CALL", Ref("sub")),
        ("LDAI", POISON), ("OUT",), ("HALT",),      # trap: CALL never jumped
        "sub",
        ("LDA", *_addr(STACK_TOP - 1)),             # pushed PC_LO
        ("OUT",), ("HALT",),                        # RAW -- no comparison
    ]


CALLRAW_PROGRAM = _build_callraw()

# ---- call — THE RETURN ADDRESS IS THE OBSERVABLE -----------------------
# The phase-C counterpart to `pads`, which made the PC's LANDING ADDRESS the
# answer rather than merely whether PC_LOAD went somewhere. PROG_stack
# proves a return HAPPENED -- its OUT sits after the call and its answer is
# computed inside the subroutine, so reaching OUT at all means the address
# was pushed, stored, popped and reloaded. It does NOT prove the return
# landed on the RIGHT byte.
#
# Here the landing site IS the only thing that can produce the answer:
#
#     0x4B   RET landed exactly on `landed`
#     0xFF   it did not. Everything else in the image is HALT, and OB was
#            poisoned before the call, so any other landing reports 0xFF.
#
# THE PADDING IS LOAD-BEARING, NOT COSMETIC. 0x120 HALTs push the CALL past
# 0x00FF so the pushed return address has a NON-ZERO HIGH BYTE (0x012C). A
# short image would sit at 0x00xx, where PC_HI is 0x00 -- and a U73 that is
# dead, unlanded or stuck low delivers 0x00 too, so the return would work by
# accident and the image would pass while half the phase-C hardware was
# missing. That is the frozen-SP blindness all over again: an answer that
# does not depend on the thing under test. See sp1 vs sp2 below.
#
# HALT does not hold on this machine, so a wrong landing that hits the
# padding halts, escapes, re-halts, and OB stays 0xFF throughout.
CALL_LANDED = 0x4B          # 01001011, mirror 0xD2 — not a rail, not a palindrome
CALL_PAD = 0x120            # enough HALTs to push the CALL above 0x00FF

CALL_PROGRAM = [
    ("LDAI", POISON), ("OUT",),         # OB = 0xFF: "RET never landed here"
    ("JMP", Ref("high")),
] + [("HALT",)] * CALL_PAD + [
    "high",
    ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),
    ("CALL", Ref("sub")),
    "landed",                           # return address 0x012C, PC_HI = 0x01
    ("LDAI", CALL_LANDED), ("OUT",), ("HALT",),
    "sub",
    ("RET",),
]

# ---- sp2 / sp3 — THE IMAGES THAT ARE NOT BLIND TO A FROZEN SP ----------
# Both earned their place on 2026-08-24, when PROG_sp1 PASSED on a machine
# whose stack pointer had never moved at all.
#
# THE BLINDNESS. PROG_sp1 pushes to [SP] and pops from [SP]. If SP never
# counts, the push and the pop use the SAME cell and the byte round-trips
# perfectly. 0x2C comes back either way. PROG_sp1 cannot tell a working
# stack from a stack pointer wired to nothing, and for most of that session
# it reported a green machine while every bank-1 decoder output was dead.
#
# That is the mirror-witness rule pointed at the SP: a round trip through
# one address is permutation-blind in the address, not just in the data.
#
# Neither image is redundant with PROG_sp. PROG_sp answers 0x00 when SP is
# frozen -- correct, but 0x00 is also what a dead REG_B, a dead SUB or a
# dead POP produces, so it names nothing. These two name the address.

SP_SENTINEL_BELOW = 0xA5        # planted where push #2 must land
SP_SENTINEL_ABOVE = 0x22        # planted one cell ABOVE the stack top
SP_SENTINEL_AT = 0x11           # planted where a pre-increment pop would read

# sp2 — DOES SP MOVE AT ALL? Plant a sentinel in the cell the SECOND push
# must hit, push twice, then read that cell by ABSOLUTE address so the
# readback cannot inherit the fault under test.
#
#     0x53  push #2 reached 0x80FE -- SP decremented
#     0xA5  push #2 hit 0x80FF too -- SP never moved, sentinel survived
SP2_PROGRAM = [
    ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),        # SP = 0x80FF
    ("LDAI", SP_SENTINEL_BELOW), ("STA", *_addr(STACK_TOP - 1)),
    ("LDAI", STACK_PUSH_A), ("PUSHA",),                 # [0x80FF]=0x2C, SP--
    ("LDAI", STACK_PUSH_B), ("PUSHA",),                 # [0x80FE]=0x53 IF SP moved
    ("LDA", *_addr(STACK_TOP - 1)),                     # absolute — SP not involved
    ("OUT",), ("HALT",),
]

# sp3 — WHICH CELL DID THE POP READ? One push, one pop, with a DIFFERENT
# sentinel in each cell the pop could wrongly reach, so the answer names the
# address instead of returning uninitialised RAM that varies by power cycle.
#
#     0x2C  correct
#     0x11  read 0x80FE -- SP_UP never took effect before the MAR copy
#     0x22  read 0x8100 -- the increment landed twice
#
# 0x22 is what a ringing CLK edge at U63.2 produced on 2026-08-24 before the
# 100R source series termination went in; see .git/sdd/CLOCK_DISTRIBUTION.md.
SP3_PROGRAM = [
    ("LXISP", STACK_TOP & 0xFF, STACK_TOP >> 8),        # SP = 0x80FF
    ("LDAI", SP_SENTINEL_AT), ("STA", *_addr(STACK_TOP - 1)),
    ("LDAI", SP_SENTINEL_ABOVE), ("STA", *_addr(STACK_TOP + 1)),
    ("LDAI", STACK_PUSH_A), ("PUSHA",),                 # [0x80FF]=0x2C, SP--
    ("POPA",),                                          # SP++, read 0x80FF
    ("OUT",), ("HALT",),
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

# dip — THE INTERACTIVE ONE, now through the BUS. The second addend comes off
# SW1 the same as it always did, but SW1 is no longer a SRC code: card zero
# answers at 0x4000-0x47FF and the machine reads it with a plain LDA. A is
# still 0x2F's partner and the answer is still the milestone's 0x4D, so a
# wrong answer points squarely at the card-zero decode -> '244 -> W path.
#
# THE OPERANDS SWAP REGISTERS AND THAT IS FORCED, NOT COSMETIC. IN was
# src=SW, dst=REG_B; LDA is src=RAM, dst=REG_A. REG_B is IMMEDIATE-ONLY --
# LDBI and IN are the only two instructions that write it, and IN is gone --
# so the card byte HAS to land in A and the constant HAS to come from LDBI.
# ADD is commutative, so 0x1E + 0x2F is the same 0x4D as 0x2F + 0x1E, and the
# instruction count is unchanged at 7 (ends = 6, same as PROG_real).
#
# SW1 IS ACTIVE LOW: R17-R24 pull IS0-7 to +5V and the switch pulls down, so
# the byte the '244 puts on W has a 0 wherever a switch is CLOSED. To present
# 0x1E = 0b00011110, CLOSE the switches for bits 0, 5, 6 and 7.
DIP_SW = ADDEND_B                       # 0x1E, presented on SW1

DIP_PROGRAM = [
    ("LDAI", POISON), ("OUT",),         # destroy the previous answer first
    ("LDA", *_addr(DIP_BASE)),          # A <- card zero = SW1  (TMP_A too)
    ("LDBI", ADDEND_A),                 # B = 0x2F, from ROM    (TMP_B too)
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


def _cylon_delay(tag, outer_n=None, inner_n=0xFF):
    """Nested count-down delay, inlined. Labels are per-frame because there
    is no CALL/RET to share one copy with.

    The counts are parameters ONLY so a host test can build a fast variant
    of the same program; the defaults reproduce the burned image byte for
    byte, and PROG_cylon's pinned CRC is what enforces that."""
    outer_n = CYLON_OUTER_N if outer_n is None else outer_n
    return [
        ("LDAI", outer_n), ("STA", *_addr(CYLON_OUTER)),
        f"{tag}_outer",
        ("LDAI", inner_n), ("STA", *_addr(CYLON_INNER)),
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

# ---- spcylon — cylon, but the stack is load-bearing --------------------
# Cylon proves the machine EXECUTES. This proves the STACK executes, every
# second and a half, forever, and it names the failing wire when it does not.
#
# Two parts, answering two different questions.
#
# PART 1, THE BOUNDARY PROBES. The SP is four '169s in a RIPPLE chain --
# U63 ~{TC1} -> U64.10, U64 ~{TC2} -> U65.10, U65 ~{TC3} -> U66.10 -- and a
# dead link is INVISIBLE until SP crosses the boundary that link carries.
# PROG_stack pushes twice and cannot see any of them. Rather than push 4096
# deep and hope, each probe seeds LXISP just ABOVE one boundary and steps
# across it with a burst of 8:
#
#     probe  base     descends            crosses  needs      fault
#     P1     0xFF16   0xFF14 -> 0xFF0C    0xFF10   ~TC1       0xE1
#     P2     0xFF06   0xFF04 -> 0xFEFC    0xFF00   ~TC1+2     0xE2
#     P3     0xF006   0xF004 -> 0xEFFC    0xF000   ~TC1+2+3   0xE3
#
# Each probe crosses EXACTLY the boundaries it claims (test_probe_bases_
# isolate_one_more_link_each), so the FIRST fault code to appear names the
# deepest link that still works. That is the no-blind-counters rule: a
# failing assertion has to name the lying signal, and "the dot froze" does
# not. The burst descends on the pushes and climbs back on the pops, so
# ~{SP_UP} and ~{SP_DOWN} both ripple the chain.
#
# The sentinels are the mirror-witness rule applied to the stack: two
# DIFFERENT bytes pushed from A and B, popped back into SWAPPED registers,
# and SUBTRACTED. 0x53-0x2C = 0x27 for a correct LIFO, 0xD9 for a crossed
# one. A single push/pop round trip is self-consistent under a crossed ~TC
# cascade, a stuck direction pin AND a nibble-reversed readback -- all three
# live failure modes here. The burst pushes the COUNTER's value rather than a
# constant, so a stuck MDR bit corrupts a sentinel instead of hiding under
# eight identical bytes.
#
# PART 2, THE SWEEP. The frame table IS the stack: the outbound half pushes
# each frame as it displays it, the return half POPS them back. LIFO order is
# therefore the VISIBLE SWEEP DIRECTION -- a stuck ~{SP_DOWN} or a crossed
# pop makes the dot scramble or walk backwards, readable across the room with
# no instruments. Every stack access also copies SP into MAR (Route B), so
# U67/U68 are exercised by all of it; a dead or hi/lo-swapped readback '245
# lands the byte at the wrong address and a sentinel catches it.
#
# COST: the probes are 3 x (8 pushes + 8 pops) ~= 1010T ~= 1.0ms against a
# ~1.4s sweep. They re-run EVERY sweep rather than once at boot, which is
# what makes this a soak: an intermittent link, a marginal ~{SP_CE} level or
# a wire that only fails warm gets retested every second and a half.
#
# PHASE B ONLY. No CALL/RET, so it runs the day U63-U69 land and does not
# wait on U72/U73.
SPCY_SENTINEL_A = 0x2C          # pushed from A, popped back into B
SPCY_SENTINEL_B = 0x53          # pushed from B, popped back into A
SPCY_EXPECT = (SPCY_SENTINEL_B - SPCY_SENTINEL_A) & 0xFF        # 0x27
SPCY_BURST = 8                  # enough to cross one boundary, no more --
                                # a deeper burst blurs WHICH link failed
SPCY_CNT = RAM_BASE + 0x12      # clear of CYLON_INNER/OUTER at 0x10/0x11
SPCY_STACK = 0xFFFF             # the sweep's own stack, clear of every probe
SPCY_PROBES = ((0xFF16, 0xE1),  # ~TC1        U63.15 -> U64.10
               (0xFF06, 0xE2),  # ~TC2        U64.15 -> U65.10
               (0xF006, 0xE3))  # ~TC3        U65.15 -> U66.10


def _sp_probe(base, tag):
    """One boundary probe. Falls through on success, jumps to `<tag>_fault`
    on a sentinel mismatch."""
    return [
        ("LXISP", *_addr(base)),
        ("LDAI", SPCY_SENTINEL_A), ("PUSHA",),      # [base]   = 0x2C
        ("LDBI", SPCY_SENTINEL_B), ("PUSHB",),      # [base-1] = 0x53
        ("LDAI", SPCY_BURST), ("STA", *_addr(SPCY_CNT)),
        f"{tag}_push",                              # descend across the line
        ("LDA", *_addr(SPCY_CNT)), ("PUSHA",),
        ("LDBI", 0x01), ("SUB",), ("STA", *_addr(SPCY_CNT)),
        ("JNZ", Ref(f"{tag}_push")),
        ("LDAI", SPCY_BURST), ("STA", *_addr(SPCY_CNT)),
        f"{tag}_pop",                               # climb back across it
        ("POPA",),
        ("LDA", *_addr(SPCY_CNT)), ("LDBI", 0x01), ("SUB",),
        ("STA", *_addr(SPCY_CNT)),
        ("JNZ", Ref(f"{tag}_pop")),
        ("POPA",),                                  # A <- 0x53, B's byte
        ("POPB",),                                  # B <- 0x2C, A's byte
        ("SUB",),                                   # 0x27 ok, 0xD9 crossed
        ("LDBI", SPCY_EXPECT), ("SUB",),            # zero iff correct
        ("JNZ", Ref(f"{tag}_fault")),
    ]


def _build_spcylon(outer_n=None, inner_n=0xFF):
    """Probes, then the stack-driven sweep, forever. The delay counts are
    parameters so the host test can run a full sweep in a few thousand
    interpreted steps; the burned image uses the defaults."""
    out_half = CYLON_FRAMES[:8]                     # 0x01 .. 0x80, pushed
    back_half = CYLON_FRAMES[8:]                    # 0x40 .. 0x02, popped
    prog = ["top"]
    for i, (base, _fault) in enumerate(SPCY_PROBES):
        prog += _sp_probe(base, f"p{i}")

    prog += [("LXISP", *_addr(SPCY_STACK))]
    for i, frame in enumerate(out_half):
        prog += [("LDAI", frame), ("OUT",), ("PUSHA",)]
        prog += _cylon_delay(f"o{i}", outer_n, inner_n)
    # the top of the stack is 0x80, which the outbound half just showed --
    # drop it so the return sweep starts on 0x40 and the eye never stalls
    prog += [("POPA",)]
    for i in range(len(back_half)):
        prog += [("POPA",), ("OUT",)] + _cylon_delay(f"b{i}", outer_n, inner_n)
    prog += [("POPA",)]                 # drop 0x01: pushes and pops balance
    prog += [("JMP", Ref("top"))]

    # Fault stubs live PAST the JMP so success never falls into them. HALT
    # does not hold on this machine, but past HALT is 0xFF fill which
    # re-halts, and U35 has no reset -- so OB keeps showing the code.
    for i, (_base, fault) in enumerate(SPCY_PROBES):
        prog += [f"p{i}_fault", ("LDAI", fault), ("OUT",), ("HALT",)]
    return prog


SPCYLON_PROGRAM = _build_spcylon()


# ---- swdemo — the machine READS THE BENCH AND BRANCHES ON IT -----------
# Not a coverage image and deliberately NOT in COVERAGE: both arms are
# infinite displays, so there is no (OB, END) fingerprint for the ladder to
# match. Same reason cylon and spcylon are excluded.
#
# What it is FOR: every other image is a fixed film strip. This one makes a
# DECISION from outside the machine, every pass, and both outcomes are
# stack-driven. It is the first image where the operator is inside the loop.
#
#     SW1 bit 0 = 1   ->  cylon sweep, the frame table IS the stack
#     SW1 bit 0 = 0   ->  interleaved blink, 0x55 <-> 0xAA
#
# SW1 IS ACTIVE LOW. R17-R24 pull IS0-7 to +5V and the switch pulls DOWN, so
# the '244 presents a 0 wherever a switch is CLOSED:
#
#     switch 0 OPEN    -> bit 0 reads 1 -> SWEEP
#     switch 0 CLOSED  -> bit 0 reads 0 -> BLINK
#
# The test sits at `top`, INSIDE the loop, not before it — so flipping the
# switch changes the display at the end of the current pass rather than
# needing a reset. That is the whole point of the image: it is the first
# thing this machine does that responds to you while it runs.
#
# BIT 0 ALONE, not the whole byte. `LDA <card zero>; LDBI 0x01; AND` leaves
# A = SW1 & 1,
# so bits 1-7 are ignored and the other seven switches stay free for
# whatever the next image wants. A JNZ on the masked value is the branch.
#
# BOTH ARMS BALANCE THE STACK. Blink pushes 2 and pops 2; sweep pushes 8 and
# pops 8 (six shown, two dropped at the ends so the eye never stalls). SP is
# therefore back where LXISP put it every time control reaches `top`, and an
# unbalanced arm would walk SP down through RAM and name itself within a few
# seconds by scribbling over CYLON_INNER/OUTER and freezing the delay.
SWDEMO_STACK = 0xFFFF               # top of RAM, clear of every scratch cell
SWDEMO_BLINK_A = 0xAA               # 0b10101010, pushed FIRST
SWDEMO_BLINK_B = 0x55               # 0b01010101, pushed SECOND -> shown first
SWDEMO_MASK = 0x01                  # bit 0 only


def _build_swdemo(outer_n=None, inner_n=0xFF):
    """Read SW1 bit 0 every pass and run one of two stack-driven displays.

    The delay counts are parameters so a host test can run both arms in a
    few thousand interpreted steps; the burned image uses the defaults and
    the pinned CRC is what enforces that."""
    out_half = CYLON_FRAMES[:8]                     # 0x01 .. 0x80, pushed
    back_half = CYLON_FRAMES[8:]                    # 0x40 .. 0x02, popped

    prog = [
        ("LXISP", *_addr(SWDEMO_STACK)),
        "top",
        ("LDA", *_addr(DIP_BASE)),  # A <- card zero = SW1  (TMP_A too)
        ("LDBI", SWDEMO_MASK),      # B = 0x01             (TMP_B too)
        ("AND",),                   # A = SW1 & 0x01 -- bit 0 alone
        ("JNZ", Ref("sweep")),      # non-zero = switch OPEN = sweep
    ]

    # ---- blink arm: bit 0 = 0. Two frames through the stack, so even the
    # simplest display proves LIFO order: 0xAA goes in first and comes back
    # SECOND. A broken stack shows 0xAA then 0x55 and names itself.
    prog += [
        ("LDAI", SWDEMO_BLINK_A), ("PUSHA",),
        ("LDAI", SWDEMO_BLINK_B), ("PUSHA",),
        ("POPA",), ("OUT",),
    ] + _cylon_delay("k0", outer_n, inner_n) + [
        ("POPA",), ("OUT",),
    ] + _cylon_delay("k1", outer_n, inner_n) + [
        ("JMP", Ref("top")),
    ]

    # ---- sweep arm: bit 0 = 1. The outbound half PUSHes each frame as it
    # shows it and the return half POPs them back, so LIFO order IS the
    # visible sweep direction.
    prog += ["sweep"]
    for i, frame in enumerate(out_half):
        prog += [("LDAI", frame), ("OUT",), ("PUSHA",)]
        prog += _cylon_delay(f"s{i}", outer_n, inner_n)
    prog += [("POPA",)]                 # drop 0x80, just shown
    for i in range(len(back_half)):
        prog += [("POPA",), ("OUT",)] + _cylon_delay(f"r{i}", outer_n, inner_n)
    prog += [("POPA",)]                 # drop 0x01: pushes and pops balance
    prog += [("JMP", Ref("top"))]
    return prog


SWDEMO_PROGRAM = _build_swdemo()

# ---- window witness -----------------------------------------------------
# THE ONLY POSITIVE PROOF THAT PHASE E'S WINDOW EXISTS. One burn, read twice,
# with the ~{ROM_SEL} wire landed between the readings.
#
# IT MUST FETCH. LDA is src=RAM and U24.22 ~OE is ~{ROM_OUT}, asserted only
# by src=ROM -- so LDA has never enabled U24's outputs and an LDA-based
# witness would read garbage BEFORE the mod. Fetch is PC-addressed and is the
# only path that ever reached 0x4000-0x7FFF.
#
# THE POISON IS NOT 0xFF. POISON, SAFE_FILL, HALT and IO_PARK are all 0xFF;
# poisoning with it would make the AFTER reading indistinguishable from a
# machine that never executed the JMP. 0x5A is the sentinel's complement, so
# a bit-reversed or nibble-swapped OB names itself.
#
# 0xA5 is also DIAG_ZERO. That is cosmetic -- this is not the diag image and
# build_window plants the sentinel at 0x4000, not at 0.
WINDOW_POISON   = 0x5A
WINDOW_SENTINEL = 0xA5

WINDOW_PROGRAM = [
    ("LDAI", WINDOW_POISON), ("OUT",),      # OB = 0x5A before anything else
    ("JMP", *_addr(IO_BASE)),               # fetch crosses 0x4000 HERE
]

WINDOW_UPPER = [
    ("LDAI", WINDOW_SENTINEL), ("OUT",),    # only reachable if U24 answers
    ("HALT",),
]


def build_window():
    """Two segments: the jump at 0x0000, the sentinel at 0x4000."""
    lo = assemble(WINDOW_PROGRAM)
    hi = assemble(WINDOW_UPPER)
    if len(lo) > IO_BASE:
        raise BuildError("window witness low segment reaches 0x4000")
    if IO_BASE + len(hi) > ROM_IMAGE:
        raise BuildError("window witness upper segment overruns the part")
    if lo[0] == DIAG_ZERO:
        raise BuildError("program byte 0 collides with the diag signature")
    img = bytearray([SAFE_FILL]) * ROM_IMAGE
    img[:len(lo)] = lo
    img[IO_BASE:IO_BASE + len(hi)] = hi
    return bytes(img)

# images whose answer depends on the switches. Everything else is read with
# the default, and the rig is told the setting rather than left to guess.
# ramexec — THE PHASE-D WITNESS. The first image in this machine's life
# whose PC ever goes above 0x7FFF, and therefore the first time FETCH_RAM
# is ever high.
#
# WHY IT IS NOT PERMUTATION-BLIND. If the fetch silently still comes from
# ROM, PC=0x9000 presents A0-A14 = 0x1000 to U24, which is 0xFF fill, which
# is HALT -- so OB keeps the poison and reads 0xFF. The answer byte cannot
# be produced by anything in ROM: 0x6E is computed inside the RAM program
# and appears nowhere as a literal.
#
# WHY THE PLANT IS VERIFIED FIRST. Unwritten RAM reads 0x00, and 0x00 is
# NOP -- so a failed plant does not fail, it NOP-slides through 28KB of RAM
# and wraps. That would look like a fetch fault while actually being a
# store fault. The read-back names which one it is.
RAMEXEC_AT     = RAM_BASE + 0x1000              # 0x9000, clear of the stack
RAMEXEC_A      = 0x8B                           # planted in A by ROM
RAMEXEC_B      = 0x1D                           # the RAM program's immediate
RAMEXEC_EXPECT = (RAMEXEC_A - RAMEXEC_B) & 0xFF # 0x6E, computed in RAM
RAMEXEC_BAD_PLANT = 0xB1

# The program that will live in RAM: LDBI imm; SUB; OUT; HALT.
# Built from OPCODES so no opcode byte is ever retyped.
RAMEXEC_CODE = [
    OPCODES["LDBI"], RAMEXEC_B,
    OPCODES["SUB"],
    OPCODES["OUT"],
    OPCODES["HALT"],
]

RAMEXEC_PROGRAM = [
    # POISON FIRST. U35 has no reset and the machine free-runs at power-up,
    # so OB holds the previous image's answer. Every failure mode of this
    # image ends without reaching an OUT, so the poison IS the fault report.
    ("LDAI", POISON), ("OUT",),
] + [
    step
    for i, b in enumerate(RAMEXEC_CODE)
    for step in (("LDAI", b), ("STA", *_addr(RAMEXEC_AT + i)))
] + [
    # Verify byte 0 landed, by ABSOLUTE address. A store fault and a fetch
    # fault both end at 0xFF otherwise, and they are different repairs.
    ("LDA", *_addr(RAMEXEC_AT)),
    ("LDBI", RAMEXEC_CODE[0]),
    ("SUB",),                                   # Z set iff the plant is good
    ("JNZ", Ref("plant_bad")),
    ("LDAI", RAMEXEC_A),                        # the operand RAM code works on
    ("JMP", *_addr(RAMEXEC_AT)),                # <-- PC crosses 0x8000 HERE
    ("HALT",),                                  # JMP never jumped -> 0xFF
    "plant_bad",
    ("LDAI", RAMEXEC_BAD_PLANT), ("OUT",), ("HALT",),
]


# ======================================================================
# PHASE F WITNESSES, 2026-08-27. SECTION 8 step 4 of .git/sdd/PHASE_F.md,
# in the order it names, and each one names its OWN failure rather than
# reporting a bare mismatch.
#
# THESE ARE PROGRAM ROMS, NOT MICROCODE. They ride a U24 burn, which is a
# different chip and a different burn event from U9/U15/U23. Do not read
# "the phase F burn" as one operation.
# ======================================================================

# ---- PROG_jnc: the '157 in one image ---------------------------------
# The ONLY image in the whole set whose answer depends on U77. Everything
# else in phase F is microcode and would pass with the mux unlanded.
#
# TWO IMAGES, NOT ONE, AND THAT IS THE POINT. A one-sided branch test is
# passed by a branch wired PERMANENTLY TAKEN -- which is exactly what a
# floating CW21 or a shorted U77.4 would produce. `jnc` must take the
# branch and `jncswap` must not, with the same code and swapped operands.
#
#   0x6C   taken     A < B unsigned, FLAG_C = 0, U77 selected I0 = FLAG_C
#   0xEE   not taken A >= B
#
# and each image reports the OTHER one's answer when it is wrong, so the
# pair reads as a direction rather than a pass/fail.
JNC_LO   = 0x10                 # the smaller operand
JNC_HI   = 0x20                 # the larger
# 0x6C and 0xEE, not the 0x5A PHASE_F SECTION 8 writes: 0x5A IS ITS OWN
# BIT-REVERSAL and every coverage answer must differ from its mirror. That
# rule came from the flipped PORTF->MDR bank, which every round-trip test
# passed. The document's constant is illustrative; the rule is not.
JNC_TAKEN     = 0x6C            # mirror 0x36
JNC_NOT_TAKEN = 0xEE            # mirror 0x77


def _jnc_image(a, b):
    """CMP then JNC. CMP is src=ALU dst=NONE, so A survives the compare --
    that is the whole reason CMP exists and it is asserted by the fact that
    neither arm reloads A before OUT... except that both arms DO reload A,
    because OB is the only observable and the arms have to differ. A's
    survival is witnessed by PROG_jnc's sibling in the host tests, not here.
    """
    return [
        ("LDAI", POISON), ("OUT",),         # U35 has no reset: poison OB first
        ("LDAI", a), ("LDBI", b),
        ("CMP",),                           # SUB with no destination
        ("JNC", Ref("hit")),
        ("LDAI", JNC_NOT_TAKEN), ("OUT",), ("HALT",),
        "hit",
        ("LDAI", JNC_TAKEN), ("OUT",), ("HALT",),
    ]


JNC_PROGRAM = _jnc_image(JNC_LO, JNC_HI)          # 0x10 <  0x20 -> taken
JNCSWAP_PROGRAM = _jnc_image(JNC_HI, JNC_LO)      # 0x20 >= 0x10 -> not taken

# ---- PROG_mov: LDCI executes for the first time ----------------------
# CLAUDE.md has carried "LDCI and NOP have never executed" since the machine
# was built, and LDCI was unreachable BY DESIGN -- C is RET's return-address
# scratch and nothing could read it back. MOV A,C is one microcode row and
# it closes that. This image is the first time in this machine's life that
# a byte goes into C and comes back out.
#
#   0x9C   LDCI wrote C and MOV A,C read it back
#   0x00   C never took the byte, or MOV A,C sourced nothing
#   0xFF   the image never reached its OUT
MOV_SENTINEL = 0x9C             # mirror 0x39; 0x5A is its own mirror
MOV_PROGRAM = [
    ("LDAI", POISON), ("OUT",),
    ("LDAI", 0x00),                     # A must be CLEARED first, or a dead
                                        # MOV A,C would report LDAI's byte
    ("LDCI", MOV_SENTINEL),
    ("MOVAC",),
    ("OUT",), ("HALT",),
]

# ---- PROG_ptr: B:C as an index pair ----------------------------------
# PROG_sp3's DISCIPLINE, AND IT IS NOT OPTIONAL. A pointer test that reads
# back through the same pointer is blind in the pointer: PROG_sp1 reported a
# green machine for most of 2026-08-24 while every bank-1 decoder output was
# dead, because it pushed to [SP] and popped from [SP] and a stuck SP uses
# the same cell twice.
#
# So: three cells, a DIFFERENT sentinel in each, planted through B:C with
# STAX -- then one read back through the pointer (LDAX) and one read back by
# ABSOLUTE address (LDB), and the answer is their DIFFERENCE. The absolute
# read cannot inherit a pointer fault, so the two paths disagree exactly when
# the pointer is wrong.
#
#   0x22   PASS: LDB read 0x33 at ptr+2 absolutely, LDAX read 0x11 at ptr+0
#   0xCD   the plant never walked -- all three STAX hit ptr+0, so ptr+2 is
#          unwritten (0x00) and ptr+0 holds the LAST sentinel
#   0x11   LDAX read ptr+1
#   0x33   LDAX read an unwritten cell
#   0xEF   LDB read nothing -- the absolute path is broken, not the pointer
#   0x00   both paths returned the SAME byte, which is a pointer collapse
#   0xFF   never reached the OUT
PTR_BASE = RAM_BASE + 0x200                 # 0x8200, clear of stack and mem
PTR_CELLS = (0x11, 0x22, 0x33)
PTR_PROGRAM = [
    ("LDAI", POISON), ("OUT",),
] + [
    step
    for i, v in enumerate(PTR_CELLS)
    for step in (("LDBI", (PTR_BASE + i) >> 8),      # B = pointer HIGH
                 ("LDCI", (PTR_BASE + i) & 0xFF),    # C = pointer LOW
                 ("LDAI", v),
                 ("STAX",))                          # [B:C] = A
] + [
    # read cell 0 THROUGH the pointer
    ("LDBI", PTR_BASE >> 8), ("LDCI", PTR_BASE & 0xFF),
    ("LDAI", 0x00),                         # clear A: a dead LDAX must not
                                            # report the sentinel it planted
    ("LDAX",),                              # A <- [B:C] = 0x11 if correct
    # read cell 2 by ABSOLUTE address -- this path cannot inherit a pointer
    # fault, which is the whole reason it is here rather than a second LDAX
    ("LDB", *_addr(PTR_BASE + 2)),          # B <- 0x33 if the plant walked
    ("BSUB",),                              # B - A
    ("OUT",), ("HALT",),
]

# ---- PROG_shl: the four TMP-shadow instructions in one OB ------------
# SHL/INR/DCR/NOT all lean on the same mechanism -- LE_TMP_B =
# NOR(~{REG_B_LOAD}, CLK), so the shadow follows the LOAD STROBE and not the
# opcode -- and all four clobber B.
#
# THE SEQUENCE IS CHOSEN SO NO TWO FAULTS CANCEL. Two INRs and one DCR, not
# one of each: INR followed by DCR would return the same byte whether both
# worked or neither did, which is the round-trip blindness that made
# PROG_sp1 useless.
#
#   0xA4   PASS
#   0xD0   SHL dead   (0x2C -> 0x2D -> 0x2E -> NOT 0xD1 -> DCR 0xD0)
#   0xA6   both INRs dead
#   0x59   NOT dead
#   0xA5   DCR dead
#   0xFF   never reached the OUT
SHL_START = 0x2C
SHL_PROGRAM = [
    ("LDAI", POISON), ("OUT",),
    ("LDAI", SHL_START),
    ("SHL",),                               # 0x2C + 0x2C = 0x58
    ("INR",), ("INR",),                     # 0x5A
    ("NOT",),                               # 0xA5
    ("DCR",),                               # 0xA4
    ("OUT",), ("HALT",),
]


# ---- PROG_ind / PROG_indst / PROG_indj: MEMORY-INDIRECT ---------------
# THE ONLY NEW ADDRESSING MODE PHASE F+ ADDS, and the only family in it that
# earns its own images. Everything else phase F+ adds is an existing row with
# one field changed; this is the RET park generalised, it is the only use of
# misc=MDR_OUT outside RET, and its operand shape -- the address written
# TWICE, as `addr` then `addr+1` -- is unlike anything else in the ISA.
#
# The pointer lives in RAM. The instruction names WHERE THE POINTER IS, not
# where the data is, so a machine that ignores the indirection reads the
# POINTER BYTE and says so.
IND_PTR   = RAM_BASE + 0xA00        # where the pointer lives
IND_DATA  = RAM_BASE + 0xABC        # where it points. Low byte 0xBC is NOT a
                                    # plausible sentinel, so "read the pointer
                                    # instead of the data" is visible
IND_SENT  = 0x39                    # the byte at IND_DATA
IND_B     = 0x9C                    # B, which LDAM must NOT touch
IND_EXPECT = (IND_B - IND_SENT) & 0xFF          # 0x63

def _ind_operand(p):
    """LDAM/STAM/JMPM take the pointer's address TWICE. MAR loads only from W
    and has no increment, so the second half must be addressed explicitly --
    the assembler is what hides that from the programmer."""
    return (*_addr(p), *_addr(p + 1))

IND_PROGRAM = [
    ("LDAI", POISON), ("OUT",),
    ("MVI", *_addr(IND_PTR), IND_DATA & 0xFF),
    ("MVI", *_addr(IND_PTR + 1), IND_DATA >> 8),
    ("MVI", *_addr(IND_DATA), IND_SENT),
    ("LDBI", IND_B),                        # must survive the indirection
    ("LDAI", 0x00),                         # a dead LDAM must not report a
                                            # byte some earlier row left in A
    ("LDAM", *_ind_operand(IND_PTR)),
    ("BSUB",),                              # B - A: wrong in EITHER operand
    ("OUT",), ("HALT",),
]
#   0x63  PASS
#   0x9C  LDAM read an unwritten cell (A stayed 0x00)
#   0xE0  LDAM read the POINTER's low byte 0xBC -- no indirection happened
#   0x00  B was clobbered and happens to equal A
#   0xFF  never reached the OUT

IND_ST_SENT = 0x5B
INDST_PROGRAM = [
    ("LDAI", POISON), ("OUT",),
    ("MVI", *_addr(IND_PTR), IND_DATA & 0xFF),
    ("MVI", *_addr(IND_PTR + 1), IND_DATA >> 8),
    ("MVI", *_addr(IND_DATA), 0x00),        # clear the target FIRST, so a
                                            # STAM that never fired reads 0x00
                                            # rather than a leftover
    ("LDAI", IND_ST_SENT),
    ("STAM", *_ind_operand(IND_PTR)),
    ("LDAI", 0x00),
    ("OUTM", *_addr(IND_DATA)),             # read back by ABSOLUTE address --
                                            # the readback cannot inherit the
                                            # fault under test
    ("HALT",),
]
#   0x5B  PASS      0x00  STAM never reached IND_DATA      0xFF  no OUT

# The JMPM landing site is COMPUTED, not counted by hand. `pads` is the image
# that made this a rule: when the PC's LANDING ADDRESS is the observable, a
# hand-counted offset is a second thing that can be wrong, and the two
# failures are indistinguishable at OB.
INDJ_MISS = 0xE7                            # fall-through: JMPM did not jump
INDJ_HIT  = 0x6C                            # mirror 0x36


def _indj(land):
    return [
        ("LDAI", POISON), ("OUT",),
        ("MVI", *_addr(IND_PTR), land & 0xFF),
        ("MVI", *_addr(IND_PTR + 1), land >> 8),
        ("JMPM", *_ind_operand(IND_PTR)),
        ("LDAI", INDJ_MISS), ("OUT",), ("HALT",),
        "landing",
        ("LDAI", INDJ_HIT), ("OUT",), ("HALT",),
    ]


# size the prologue with a placeholder, then rebuild with the real target
INDJ_LAND = len(assemble(_indj(0x0000)[:-4]))
INDJ_PROGRAM = _indj(INDJ_LAND)
#   0x6C  PASS -- the PC landed where the RAM pointer said
#   0xE7  JMPM fell through: the indirection or the PC_LOAD did not happen
#   0xFF  never reached either OUT

# ---- PHASE G -- the serial card's witnesses ------------------------------
# Eight images, PHASE_G.md SECTION 3, plus serprobe from step 2. Every one
# starts with the poison: U35 has no reset, so OB holds the previous answer
# until something overwrites it, and 0xFF is what a program that never
# reached its OUT leaves behind.
#
# TWO have an oracle (serid, serid_aa): they touch only SCR. The other
# SEVEN are in SERIAL_WITNESS, not COVERAGE, and simulate() REFUSES them --
# see the ruling above io_read(). Their expected bytes are copied from the
# datasheet with the table or section named beside each. A human compares
# a byte on the LEDs against a sourced constant; that is not the same thing
# as --expected checking it, and it is reported as "datasheet-sourced,
# unoracled" every time.
SER_POISON = [("LDAI", POISON), ("OUT",)]

# 4b -- the scratch register. RAW REPORT: the byte names its own broken line.
# 0x54 = D0 stuck, 0x51 = D2, 0x15 = D6; 0xFF = the card never drove W;
# 0x00 = something drove W low but not with the byte. The two arms between
# them put both a 1 and a 0 on every data line.
SERID_VALUE = 0x55
SERID_AA_VALUE = 0xAA


def _serid(value):
    return SER_POISON + [
        ("LDAI", value), ("STA", *_addr(SER_SCR)),
        ("LDA", *_addr(SER_SCR)), ("OUT",), ("HALT",),
    ]


SERID_PROGRAM = _serid(SERID_VALUE)
SERID_AA_PROGRAM = _serid(SERID_AA_VALUE)


def ser_init(mcr=0x00):
    """SECTION 4 -- 9600 8N1, FIFO on, polled. 14 instructions, 35 bytes.

    ORDER IS LOAD-BEARING (GOTCHA 1): LCR bit 7 is DLAB, which banks base+0
    and base+1 to the divisor latches. IER lives at base+1 and is written
    AFTER the LCR write that clears DLAB; written before it, the byte lands
    in DLM and changes the baud rate silently. MCR is last so the loopback
    arm (0x10) and the real arm (0x00) differ in exactly one byte."""
    return [
        ("LDAI", 0x83), ("STA", *_addr(SER_LCR)),   # DLAB | 8N1
        ("LDAI", 0x18), ("STA", *_addr(SER_DLL)),   # 3686400/(16*9600) = 24
        ("LDAI", 0x00), ("STA", *_addr(SER_DLM)),
        ("LDAI", 0x03), ("STA", *_addr(SER_LCR)),   # 8N1, DLAB clear
        ("LDAI", 0x07), ("STA", *_addr(SER_FCR)),   # FIFO on, both cleared
        ("LDAI", 0x00), ("STA", *_addr(SER_IER)),   # polled mode, 8.12
        ("LDAI", mcr),  ("STA", *_addr(SER_MCR)),
    ]


SER_MASK_DR = 0x01              # LSR bit 0: a byte is in the RCVR FIFO
SER_MASK_THRE = 0x20            # LSR bit 5: the XMIT FIFO is empty


def _ser_poll(tag, mask):
    """SECTION 4's poll loop, 16 T-states per non-taken pass. AND sets Z and
    Z HOLDS through LDA/LDBI/JNZ (none is an ALU source), so the taken arm
    is "the masked bit is SET". The ISA has JNZ and no JZ, so the back edge
    is a JMP and cannot fall through."""
    return [
        f"wait_{tag}",
        ("LDA", *_addr(SER_LSR)), ("LDBI", mask), ("AND",),
        ("JNZ", Ref(f"ready_{tag}")),
        ("JMP", Ref(f"wait_{tag}")),
        f"ready_{tag}",
    ]


# step 2 -- U101 only, U102/U103 NOT fitted. Nothing on the card drives W,
# so 0x4800 reads the park. With U103 seated this reads RBR and means nothing.
SERPROBE_PROGRAM = SER_POISON + [
    ("LDA", *_addr(SER_BASE)), ("OUT",), ("HALT",),
]

# 4c -- bytes the UART GENERATED and DINO never wrote. Narrows the
# permutation-blind scratch round trip; step 7 closes it.
SERLSR_PROGRAM = SER_POISON + [
    ("LDA", *_addr(SER_LSR)), ("OUT",), ("HALT",),
]
SERIIR_PROGRAM = SER_POISON + [
    ("LDAI", 0x07), ("STA", *_addr(SER_FCR)),
    ("LDA", *_addr(SER_IIR)), ("OUT",), ("HALT",),
]

# step 5 -- the divisor dance and nothing else. Witness is a scope on
# U103.15: 153.6 kHz = 3686400 / 24. Wrong frequency names which latch
# took the wrong byte; nothing at all means DLAB never banked the latches.
SERBAUD_PROGRAM = SER_POISON + [
    ("LDAI", 0x83), ("STA", *_addr(SER_LCR)),
    ("LDAI", 0x18), ("STA", *_addr(SER_DLL)),
    ("LDAI", 0x00), ("STA", *_addr(SER_DLM)),
    ("LDAI", 0x03), ("STA", *_addr(SER_LCR)),
    ("HALT",),
]

# step 6 -- internal loopback. MCR bit 4 ties SOUT to SIN inside the part;
# no wire leaves the card. 0x53 and not 0x3C: a byte goes LSB-first and a
# bus reversed end to end returns a palindrome unchanged. 0x53 -> 0xCA.
SERLOOP_BYTE = 0x53
SERLOOP_PROGRAM = SER_POISON + ser_init(mcr=0x10) + [
    ("LDAI", SERLOOP_BYTE), ("STA", *_addr(SER_THR)),
] + _ser_poll("dr", SER_MASK_DR) + [
    ("LDA", *_addr(SER_RBR)), ("OUT",), ("HALT",),
]

# step 7 -- real TX. THE MIRROR-WITNESS: the host terminal decodes the bits
# by a convention DINO cannot influence, so no permutation of the card's
# data bus survives it. OB = 0x53 only says the program finished.
SERTX_TEXT = b"DINO\r\n"
SERTX_DONE = 0x53


def _sertx():
    prog = SER_POISON + ser_init(mcr=0x00)
    for i, ch in enumerate(SERTX_TEXT):
        prog += _ser_poll(f"tx{i}", SER_MASK_THRE)
        prog += [("LDAI", ch), ("STA", *_addr(SER_THR))]
    prog += [("LDAI", SERTX_DONE), ("OUT",), ("HALT",)]
    return prog


SERTX_PROGRAM = _sertx()

# step 8 -- real RX, echoed. NEVER HALTS. Type a character: it lands on OB
# in binary AND comes back to the terminal, two observables per keystroke.
# THRE is polled BEFORE the RBR read so the byte goes A -> OB -> THR with
# nothing clobbering A in between; RBR is read EXACTLY ONCE (GOTCHA 2: the
# read pops the FIFO and cannot be repeated).
SERRX_PROGRAM = SER_POISON + ser_init(mcr=0x00) + [
    "top",
] + _ser_poll("rx", SER_MASK_DR) + _ser_poll("echo", SER_MASK_THRE) + [
    ("LDA", *_addr(SER_RBR)), ("OUT",), ("STA", *_addr(SER_THR)),
    ("JMP", Ref("top")),
]

# tag -> (program, expected OB or None, where the expectation comes from)
SERIAL_WITNESS = {
    "serprobe": (SERPROBE_PROGRAM, IO_PARK,
                 "step 2 only, U103 NOT seated: the park. Meaningless after"),
    "serlsr":   (SERLSR_PROGRAM, 0x60,
                 "datasheet TABLE I, LSR after Master Reset = THRE|TEMT"),
    "seriir":   (SERIIR_PROGRAM, 0xC1,
                 "datasheet 8.6: bits 7:6 = FCR0, bit 0 = nothing pending"),
    "serbaud":  (SERBAUD_PROGRAM, None,
                 "scope U103.15 ~BAUDOUT: 153.6 kHz = 3686400/24"),
    "serloop":  (SERLOOP_PROGRAM, SERLOOP_BYTE,
                 "the byte itself, back through MCR bit 4 loopback"),
    "sertx":    (SERTX_PROGRAM, SERTX_DONE,
                 "HOST TERMINAL shows DINO at 9600 8N1; OB only says done"),
    "serrx":    (SERRX_PROGRAM, None,
                 "never halts: typed char on OB AND echoed to the host"),
}

COVERAGE_SW = {"dip": DIP_SW}

COVERAGE = {
    "probe": PROBE_PROGRAM,
    "adda": ADDA_PROGRAM,
    "addb": ADDB_PROGRAM,
    "real": PROGRAM,
    "dip": DIP_PROGRAM,
    "alu": ALU_PROGRAM,
    "mem": MEM_PROGRAM,
    "flow": FLOW_PROGRAM,
    "loop": LOOP_PROGRAM,
    "mardisc": MARDISC_PROGRAM,
    "pads": PADS_PROGRAM,
    "sp1": SP1_PROGRAM,
    "sp2": SP2_PROGRAM,
    "sp3": SP3_PROGRAM,
    "sp": SP_PROGRAM,
    "calladdr": CALLADDR_PROGRAM,
    "callraw": CALLRAW_PROGRAM,
    "call": CALL_PROGRAM,
    "stack": STACK_PROGRAM,
    "ramexec": RAMEXEC_PROGRAM,
    # phase F, 2026-08-27
    "jnc": JNC_PROGRAM,
    "jncswap": JNCSWAP_PROGRAM,
    "mov": MOV_PROGRAM,
    "ptr": PTR_PROGRAM,
    "shl": SHL_PROGRAM,
    "ind": IND_PROGRAM,
    "indst": INDST_PROGRAM,
    "indj": INDJ_PROGRAM,
    # phase G, 2026-09-04 -- the two serial images the oracle CAN check
    "serid": SERID_PROGRAM,
    "serid_aa": SERID_AA_PROGRAM,
}


# ---- suite — THE WHOLE TWELVE-IMAGE REGRESSION IN ONE BURN -------------
# Card zero made the machine readable AT RUN TIME, so the choice of which
# test to run can be a DIP setting instead of a chip swap: set SW1 to 1-12,
# press RESET, read OB. Twelve ROM pulls become one, which on a breadboard
# with no ZIF on the program socket is the difference between a regression
# and a rewiring session.
#
# LAYOUT. The dispatch owns the first slot and each test gets its own,
# assembled at its own base. Assembling separately is not a detail: the
# twelve programs reuse label names ("top", "high", "sub"), so concatenating
# them into one list would collide on the first duplicate.
#
#     0x0000   dispatch, 149 bytes of it
#     0x0400   test 1 ... 0x3000   test 12       12 x 1K, all under 0x4000
#
# THE NO-MATCH ARM REPORTS THE SWITCH BYTE RAW, and that is the rule about
# raw reports beating assertions, applied to the selector itself: a setting
# that matches nothing OUTs SW1 rather than a verdict, so a stuck switch or
# an inverted bank names its own value instead of reporting "no test ran".
#
# WHAT THE SUITE DOES NOT REPLACE. Each standalone image is still generated
# and still burnable. The suite depends on card zero, so a broken card takes
# the whole regression with it; the twelve singles are the fallback and the
# reason they stay.
SUITE_SLOT = 0x0400             # 1K per test; the largest is call at 305B
SUITE_TESTS = ("mardisc", "pads", "mem", "flow", "alu", "loop",
               "sp", "sp2", "sp3", "call", "stack", "ramexec")


def _suite_dispatch(tests=SUITE_TESTS):
    """Read card zero, compare against each selector, JMP to the match.

    No indexed jump exists on this machine, so the dispatch is a compare
    chain: LDA reloads A every pass because SUB consumes it."""
    prog = []
    for sel, _tag in enumerate(tests, start=1):
        prog += [
            ("LDA", *_addr(DIP_BASE)),          # A <- SW1
            ("LDBI", sel),
            ("SUB",),                           # Z set iff SW1 == sel
            ("JNZ", Ref(f"next{sel}")),
            ("JMP", *_addr(SUITE_SLOT * sel)),
        ]
        prog.append(f"next{sel}")
    # No match: OUT the switch byte RAW. A verdict here would collapse the
    # one number that names the fault -- a stuck switch, an inverted bank or
    # a card that answered 0xFF all read as "no test ran" otherwise.
    prog += [("LDA", *_addr(DIP_BASE)), ("OUT",), ("HALT",)]
    return prog


def build_suite(tests=SUITE_TESTS):
    """One ROM image holding the dispatch and every test in `tests`."""
    img = bytearray([SAFE_FILL]) * ROM_IMAGE
    disp = assemble(_suite_dispatch(tests))
    img[0:len(disp)] = disp
    for sel, tag in enumerate(tests, start=1):
        base = SUITE_SLOT * sel
        if base + SUITE_SLOT > ROM_WINDOW:
            raise BuildError(
                f"slot {sel} starts at 0x{base:04X}, at or past the ROM "
                f"window at 0x{ROM_WINDOW:04X} -- ROM is deselected there")
        code = assemble(COVERAGE[tag], base=base)
        if len(code) > SUITE_SLOT:
            raise BuildError(
                f"{tag} is {len(code)}B and overruns its {SUITE_SLOT}B slot "
                f"-- it would scribble slot {sel + 1} and the fault would "
                f"report one slot away from its cause")
        img[base:base + len(code)] = code
    return bytes(img)


ASM_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "asm"))


def asm_owned_tags():
    """Tags that have asm/<tag>.asm. Those images belong to the assembler
    (Rico, 2026-09-04: new programs are .asm, not Python lists). The Python
    copy may stay for the oracle, but the generator must not write the file:
    on 2026-09-05 `make gen-progrom` put a 0xFF-poison serid over the
    assembled 0x99 one, and make then called the clobbered file up to date."""
    try:
        names = os.listdir(ASM_DIR)
    except FileNotFoundError:
        return set()
    return {n[:-4] for n in names if n.endswith(".asm")}


def write_coverage_images(roms):
    """Write roms/PROG_<tag>.bin for every COVERAGE tag the assembler does
    not own, and return the {tag: (crc, ob, ends, sw, needs_sw)} table for
    the C header. Skipped tags are still simulated so the table is whole."""
    owned = asm_owned_tags()
    cov = {}
    for tag, prog in COVERAGE.items():
        if tag == "real":
            continue
        img = build_image(prog)
        if tag in owned:
            print(f"  PROG_{tag}.bin: asm/{tag}.asm owns it, not written")
        else:
            with open(os.path.join(roms, f"PROG_{tag}.bin"), "wb") as f:
                f.write(img)
        r = simulate(prog, switches=COVERAGE_SW.get(tag, 0x00))
        cov[tag] = (crc16(img), r["out"], r["ends"],
                    COVERAGE_SW.get(tag, 0x00), tag in COVERAGE_SW)
    return cov


def build_image_from_bytes(code, origin=0, fill=SAFE_FILL):
    """Already-assembled bytes -> a full ROM image.

    The .asm path (asm.py) produces bytes directly, so it needs the padding
    and the two guards without going back through `assemble()`. Everything
    below build_image() shares this, so a rule added here reaches both paths.

    `fill` is what unclaimed ROM reads. HALT by default (SAFE_FILL); the
    `.fill` directive overrides it per image -- 2026-09-06, Rico's A/B of
    the fill choice. A NOP-filled ROM turns an escape from HALT into a
    28K slide that wraps to 0x0000 and RE-RUNS the program: loud where HALT
    fill re-halts one byte later and is silent.
    """
    code = bytes(code)
    if origin:
        code = bytes([fill]) * origin + code
    if len(code) > ROM_WINDOW:
        raise BuildError("program larger than the ROM WINDOW (0x0000-0x3FFF)")
    if code and code[0] == DIAG_ZERO:
        raise BuildError("program byte 0 collides with the diag signature")
    return code + bytes([fill]) * (ROM_IMAGE - len(code))


def build_image(program):
    code = assemble(program)
    if len(code) > ROM_WINDOW:
        raise BuildError("program larger than the ROM WINDOW (0x0000-0x3FFF)")
    if code[0] == DIAG_ZERO:
        raise BuildError("program byte 0 collides with the diag signature")
    return code + bytes([SAFE_FILL]) * (ROM_IMAGE - len(code))


def build_real():
    code = assemble(PROGRAM)
    if len(code) > ROM_WINDOW:
        raise BuildError("program larger than the ROM WINDOW (0x0000-0x3FFF)")
    if code[0] == DIAG_ZERO:
        raise BuildError("program byte 0 collides with the diag signature")
    return code + bytes([SAFE_FILL]) * (ROM_IMAGE - len(code))


def diag_triple_max():
    """Worst-case ambiguity of three CONSECUTIVE diag bytes: how many addresses
    can share one triple. block2.fetch proves the fetch path reads ROM at PC,
    PC+1, PC+2 by matching such a triple, so this is the threshold below which
    a match is meaningful — and it is STRUCTURAL, not luck. diag_byte truncates
    to 8 bits, so three bytes constrain 24 bits with enough structure left to
    leave a 4-fold ambiguity almost everywhere and 8-fold in places. A
    hand-picked threshold of 4 would have false-failed on 3% of positions."""
    seen = {}
    for a in range(ROM_IMAGE - 2):
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
        f"#define PR_SIZE {ROM_IMAGE}u",
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
    print("# phase G, DATASHEET-SOURCED, UNORACLED -- simulate() refuses these.")
    print("# A human reads OB against the constant; --expected did not check it.")
    for tag, (_prog, ob, source) in SERIAL_WITNESS.items():
        ob_s = f"0x{ob:02X}" if ob is not None else "-"
        print(f"{tag:<12s} {ob_s:<11s} {source}")


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
    cov = write_coverage_images(ROMS)
    # cylon is written but NOT registered in PR_COVERAGE: it never halts, so
    # it has no (OB, END) fingerprint for block4.stepped to match. Burning it
    # and running block4.stepped will correctly report "no known image".
    cyl = build_image(CYLON_PROGRAM)
    with open(os.path.join(ROMS, "PROG_cylon.bin"), "wb") as f:
        f.write(cyl)
    cyl_crc = crc16(cyl)
    cyl_len = len(assemble(CYLON_PROGRAM))
    # spcylon, same exclusion for the same reason: it never halts either.
    spc = build_image(SPCYLON_PROGRAM)
    with open(os.path.join(ROMS, "PROG_spcylon.bin"), "wb") as f:
        f.write(spc)
    spc_crc = crc16(spc)
    spc_len = len(assemble(SPCYLON_PROGRAM))
    # swdemo, same exclusion again: BOTH its arms are infinite displays, so
    # there is no single answer to fingerprint. It is also the only image
    # whose behaviour changes without a reburn — SW1 bit 0 picks the arm.
    swd = build_image(SWDEMO_PROGRAM)
    with open(os.path.join(ROMS, "PROG_swdemo.bin"), "wb") as f:
        f.write(swd)
    swd_crc = crc16(swd)
    swd_len = len(assemble(SWDEMO_PROGRAM))
    # suite — THE WHOLE TWELVE-IMAGE REGRESSION IN ONE BURN. Not in
    # COVERAGE and not fingerprinted: it has TWELVE correct answers, one per
    # DIP setting, so there is no single --expected row for it. Same
    # exclusion as cylon/spcylon/swdemo/window, for the same reason.
    suite = build_suite()
    with open(os.path.join(ROMS, "PROG_suite.bin"), "wb") as f:
        f.write(suite)
    suite_crc = crc16(suite)
    # window — THE PHASE E A/B WITNESS. Not in COVERAGE: it has TWO correct
    # answers, one per side of the ~{ROM_SEL} wire, so there is no single
    # --expected row for it. Same exclusion as cylon/spcylon/swdemo.
    win = build_window()
    with open(os.path.join(ROMS, "PROG_window.bin"), "wb") as f:
        f.write(win)
    win_crc = crc16(win)
    # phase G -- the seven UNORACLED serial witnesses. Written, burnable,
    # NOT in PR_COVERAGE and NOT in cov: simulate() refuses them, so there
    # is no (OB, END) fingerprint and no --expected row with a number in it.
    ser = {}
    for tag, (prog, ob, source) in SERIAL_WITNESS.items():
        img = build_image(prog)
        with open(os.path.join(ROMS, f"PROG_{tag}.bin"), "wb") as f:
            f.write(img)
        ser[tag] = (crc16(img), len(assemble(prog)), ob, source)
    emit_header(real, crcs, HDR, cov)
    print(f"wrote {6 + len(cov)}x {ROM_IMAGE}B bins -> {ROMS}")
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
    print(f"    PROG_spcylon.bin  crc=0x{spc_crc:04X}  {spc_len} bytes  "
          f"NEVER HALTS — 3 SP boundary probes then the stack-driven sweep; "
          f"frozen OB 0x{SPCY_PROBES[0][1]:02X}/0x{SPCY_PROBES[1][1]:02X}/"
          f"0x{SPCY_PROBES[2][1]:02X} names the dead ripple link")
    print(f"    PROG_swdemo.bin  crc=0x{swd_crc:04X}  {swd_len} bytes  "
          f"NEVER HALTS — SW1 bit 0 picks the arm every pass. "
          f"switch 0 OPEN (bit reads 1) = cylon sweep; "
          f"CLOSED (bit reads 0) = 0x{SWDEMO_BLINK_B:02X}/"
          f"0x{SWDEMO_BLINK_A:02X} interleaved blink")
    print(f"    PROG_suite.bin  crc=0x{suite_crc:04X}  "
          f"the twelve-image regression, ONE burn. SW1 = 1-{len(SUITE_TESTS)} "
          f"picks the test, RESET re-runs it, OB is the answer. A setting "
          f"outside the range OUTs SW1 raw.")
    for _sel, _tag in enumerate(SUITE_TESTS, start=1):
        _r = simulate(COVERAGE[_tag], switches=COVERAGE_SW.get(_tag, 0x00))
        print(f"      SW1={_sel:2d}  {_tag:8s} OB=0x{_r['out']:02X}")
    print(f"    PROG_window.bin  crc=0x{win_crc:04X}  "
          f"BEFORE the mod OB 0x{WINDOW_SENTINEL:02X}, "
          f"AFTER OB 0x{WINDOW_POISON:02X}")
    print("  phase G serial witnesses -- DATASHEET-SOURCED, UNORACLED:")
    for tag, (crc, n, ob, source) in ser.items():
        ob_s = f"OB 0x{ob:02X}" if ob is not None else "no OB  "
        print(f"    PROG_{tag}.bin  crc=0x{crc:04X}  {n:4d} bytes  {ob_s}  "
              f"{source}")
    print("      ONE burn, read TWICE, with ~{ROM_SEL} landed on U24.20")
    print("      between the readings. The BEFORE reading cannot be retaken.")
    print(f"  program: {' '.join(s[0] for s in PROGRAM)}"
          f"  -> OUT should show 0x{EXPECT_SUM:02X}")
    for name, val in crcs.items():
        print(f"  {name} = 0x{val:04X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
