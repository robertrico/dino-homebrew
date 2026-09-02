#!/usr/bin/env python3
"""Host tests for the progressive ISA-coverage ROMs.

The block ladder proves the machine EXECUTES. These images prove it executes
the whole of the CURRENT ISA — one image per instruction group, each ending
`OUT; HALT` because OB is the only datapath observable on the ladder.

Nothing here hand-computes an expected result. `progrom_gen.simulate()`
INTERPRETS THE BURNED MICROCODE ROWS, so the expectation and the hardware
cannot disagree by construction — the same discipline as cw_expect and
MC_REAL_WORDS. These tests check the interpreter against the ISA, then check
each image against the interpreter.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import progrom_gen as pg
from microcode_gen import OPCODES, INSTRUCTIONS

try:
    import pytest
except ImportError:                    # pragma: no cover -- plain `python3
    pytest = None                      # docs/notes/test_progrom_coverage.py`
                                        # (this file's own header) has no
                                        # pytest dependency; keep it that way.

FAILS = []


def check(cond, label):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILS.append(label)


def check_eq(got, want, label):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")
        FAILS.append(label)


def check_raises(fn, label):
    try:
        fn()
    except pg.BuildError:
        print(f"  ok   {label}")
        return
    print(f"  FAIL {label} — no BuildError")
    FAILS.append(label)


# ---- the assembler must handle labels, since flow images need them --------
def test_labels():
    print("assembler: labels and forward references")
    prog = [("JMP", pg.Ref("target")), ("HALT",), "target", ("OUT",), ("HALT",)]
    code = pg.assemble(prog)
    # JMP is 3 bytes, HALT 1 -> target is at 4
    check_eq(code[0], OPCODES["JMP"], "JMP opcode emitted")
    check_eq((code[1], code[2]), (4, 0), "forward label resolved LO,HI")
    check_eq(code[3], OPCODES["HALT"], "poison HALT still emitted")
    check_eq(code[4], OPCODES["OUT"], "label lands on the right byte")

    check_raises(lambda: pg.assemble([("JMP", pg.Ref("nope"))]),
                 "undefined label raises")
    check_raises(lambda: pg.assemble([("JMP", 1)]),
                 "JMP with one raw operand raises (microcode declares two)")


# ---- the interpreter must agree with the microcode -----------------------
def test_simulator_against_microcode():
    print("simulator is driven by the microcode, not by hand")
    # every implemented opcode must be executable by the interpreter
    for name in INSTRUCTIONS:
        check(pg.sim_supports(name), f"interpreter handles {name}")
    # the milestone is the anchor: it must reproduce the known answer
    check_eq(pg.simulate(pg.PROGRAM)["out"], pg.EXPECT_SUM,
             f"milestone simulates to 0x{pg.EXPECT_SUM:02X}")
    check_eq(pg.simulate(pg.PROGRAM)["halted"], True, "milestone halts")


def test_flags_hold_across_non_alu():
    """U48.1 S = ~{ALU_OUT}: the flag mux feeds U49 its own outputs back
    unless an ALU op is driving, so STA/LDA/JMP/OUT do not disturb Z.
    The loop image depends on this and would be unwritable without it."""
    print("flags hold across non-ALU instructions")
    prog = [
        ("LDAI", 1), ("LDBI", 1),
        ("SUB",),                       # A = 0, Z set
        ("STA", 0x00, 0x80),            # must NOT clobber Z
        ("JNZ", pg.Ref("bad")),         # must NOT be taken
        ("LDAI", 0x39), ("OUT",), ("HALT",),
        "bad", ("LDAI", 0xFF), ("OUT",), ("HALT",),
    ]
    check_eq(pg.simulate(prog)["out"], 0x39, "Z survived the STA")


# ---- the images ----------------------------------------------------------
def test_images_are_witnesses():
    """Every image's answer must be a MIRROR-WITNESS: a bit-reversed read
    (the flipped-ribbon fault that only registers.outreg ever caught) must
    produce a DIFFERENT byte. 0x00, 0xFF and palindromes are worthless."""
    print("every image's answer self-names under a flipped ribbon")
    for tag, prog in pg.COVERAGE.items():
        res = pg.simulate(prog)
        ob = res["out"]
        rev = int(f"{ob:08b}"[::-1], 2)
        check(ob is not None, f"{tag}: reaches OUT")
        check(res["halted"], f"{tag}: halts")
        check(ob not in (0x00, 0xFF), f"{tag}: answer 0x{ob:02X} is not a rail")
        check(ob != rev, f"{tag}: answer 0x{ob:02X} != its mirror 0x{rev:02X}")


def test_coverage_is_progressive():
    """Each image adds instructions the earlier ones did not use, and
    together they must reach every implemented opcode."""
    print("the ladder is progressive and complete")
    # An image earns its place by adding a new MNEMONIC or a new BEHAVIOUR.
    # `loop` adds no opcode the others lack — it adds the JNZ TAKEN arm,
    # which blocks 1-3 cannot reach at all because FLAG_Z is strapped HIGH
    # there and COND_TAKEN is pinned low. Behaviour has to be declared, so
    # that "this image is redundant" stays a question the test can answer.
    BEHAVIOUR = {
        "probe": "immediate -> A -> OB with the ALU out of the path entirely",
        "adda": "TMP_A alone: value + 0, so the answer IS the operand",
        "addb": "TMP_B alone: 0 + value, isolating the other shadow latch",
        "real": "the milestone: the machine adds two numbers",
        "dip": "an operand from the BENCH, not the ROM -- and since phase E "
               "it arrives BY ADDRESS, off card zero at 0x4000 through the "
               "published bus, rather than through a SRC code. IN retired "
               "with U28.7. First image to reach a peripheral with a plain "
               "LDA; the answer is still the milestone's own 0x4D",
        "flow": "unconditional PC_LOAD, and the JNZ NOT-taken arm",
        "loop": "the JNZ TAKEN arm, iterated an exact number of times",
        "mem": "MAR as a LATCH, not just a mux — the named gap in BRINGUP.md",
        "mardisc": "TWO DIFFERENT MAR values, not one used twice. mem stores "
                   "and loads through the SAME address (0x8000 — bit 15 alone) "
                   "and is therefore blind to what that address actually was; "
                   "this reads back the FIRST of two cells that differ only in "
                   "MAR_LO, so a collapsed low byte returns the SECOND value",
        "pads": "the PC's LANDING ADDRESS as the observable. Every 4-byte slot "
                "is LDAI <own address>; OUT; HALT, so OB names where PC_LOAD "
                "actually went rather than merely whether it went somewhere",
        "sp1": "ONE push and ONE pop — the fewest moving parts that reach the "
               "stack at all. Blind to a frozen SP by construction (push and "
               "pop use the same cell), which is exactly why sp2 exists",
        "sp2": "the ADDRESS as the observable, not the data. A sentinel in the "
               "cell push #2 must reach, read back ABSOLUTELY so the readback "
               "cannot inherit the fault. The first image that is NOT blind to "
               "a stack pointer that never moves",
        "sp3": "WHICH cell the pop read. A different sentinel in each "
               "neighbour, so an off-by-one names its direction instead of "
               "returning uninitialised RAM that varies by power cycle",
        "calladdr": "CALL WITHOUT RET. Reads the pushed return address back "
                    "out of RAM by absolute address, so it exercises the "
                    "CALL-side pins (U70.12/.13, U72, U73) while touching "
                    "none of the RET-side ones (U28.10, U29.11, U30.12). "
                    "calladdr passing and call failing puts the fault on the "
                    "RET side; without the split, PROG_call lights up five "
                    "never-asserted pins at once and names none of them",
        "callraw": "REPORTS the pushed byte instead of judging it. The image "
                   "that found phase C's fault after calladdr misattributed "
                   "it: calladdr said 0xC1 (LO byte wrong -> U72), but the raw "
                   "byte was 0x26 -- the previous JMP's target, which named "
                   "the real fault (U72/U73 landed on U11/U12, the PC LOAD "
                   "path, reading stale PCD). An assertion collapses a number "
                   "into a verdict, and the number was the clue",
        "call": "the RETURN ADDRESS as the observable — pads, for RET. "
                "stack proves a return HAPPENED; this proves it landed on "
                "the right BYTE, from above 0x00FF so the pushed PC_HI is "
                "non-zero and U73 cannot pass by delivering 0x00",
        "ramexec": "no new instruction at all -- the new thing is WHERE the "
                   "instructions come from. The PC crosses 0x8000 and the "
                   "machine fetches from RAM, which is phase D's whole "
                   "claim. The plant is verified by ABSOLUTE address first, "
                   "because unwritten RAM reads 0x00 = NOP: a failed store "
                   "would otherwise NOP-slide 28KB and present as a fetch "
                   "fault. PHASE D.",
        "stack": "WORK DONE INSIDE the subroutine and surviving the return. "
                 "call proves RET lands on the right byte but its subroutine "
                 "is a bare RET, so it says nothing about the machine's state "
                 "across a call. Here the SUB runs inside the callee and the "
                 "only OUT is after the return, so the answer exists only if "
                 "the registers, the flags and the stack all came back intact "
                 "-- and two DIFFERENT bytes popped into SWAPPED registers "
                 "make LIFO order observable rather than decorative",
        # ---- PHASE F, 2026-08-27 ----------------------------------------
        "jnc": "THE ONLY IMAGE IN THE WHOLE SET WHOSE ANSWER DEPENDS ON U77. "
               "Everything else phase F adds is microcode and would pass with "
               "the '157 unlanded. CMP sets FLAG_C, JNC selects it through "
               "CW21, and the taken arm is the only path to 0x5A",
        "jncswap": "THE OTHER DIRECTION, and it is not redundant: a one-sided "
                   "branch test is passed by a branch wired PERMANENTLY "
                   "TAKEN, which is exactly what a floating CW21 or a shorted "
                   "U77.4 produces. Same code, swapped operands, opposite "
                   "answer",
        "mov": "LDCI EXECUTES FOR THE FIRST TIME IN THIS MACHINE'S LIFE. C "
               "was write-only by design -- it is RET's return-address "
               "scratch and nothing could read it back -- so the gap was "
               "MICROCODE-SOFT and MOV A,C is the one row that closes it",
        "ptr": "B:C as an INDEX PAIR, with PROG_sp3's discipline. Three cells, "
               "a different sentinel in each, planted through the pointer and "
               "read back down TWO paths: one through the pointer (LDAX) and "
               "one by ABSOLUTE address (LDB). The absolute path cannot "
               "inherit a pointer fault, so the two disagree exactly when the "
               "pointer is wrong -- which is the blindness that let PROG_sp1 "
               "report a green machine with every bank-1 decode dead",
        "shl": "the TMP_B shadow doing ARITHMETIC. Two INRs and one DCR, not "
               "one of each: INR then DCR returns the same byte whether both "
               "worked or neither did, and no two faults in this sequence "
               "cancel",
        # ---- PHASE F+, 2026-08-27 ---------------------------------------
        "ind": "MEMORY-INDIRECT, the third addressing mode and the only new "
               "one phase F+ adds. The pointer lives in RAM and the "
               "instruction names WHERE THE POINTER IS, so a machine that "
               "ignores the indirection reads the POINTER BYTE and says so "
               "(0xE0). B is loaded before the LDAM and subtracted after, so "
               "the answer is wrong if EITHER the data or B is wrong -- the "
               "mode clobbers C by construction and must not touch B",
        "indst": "the same mode STORING, read back by ABSOLUTE address so "
                 "the readback cannot inherit the fault under test. The "
                 "target is cleared first, so a STAM that never fired reads "
                 "0x00 rather than a convincing leftover",
        "indj": "the same mode BRANCHING, with the PC's landing site as the "
                "observable -- pads, for JMPM. The landing address is "
                "COMPUTED from the assembled prologue, not counted by hand: "
                "when the landing site IS the answer, a miscounted offset "
                "and a broken jump look identical at OB",
    }
    seen = set()
    order = ["probe", "adda", "addb", "real", "dip", "alu", "mem", "flow",
             "loop", "mardisc", "pads", "sp1", "sp2", "sp3", "sp", "calladdr",
             "callraw", "call", "stack", "ramexec",
             "jnc", "jncswap", "mov", "ptr", "shl",
             "ind", "indst", "indj"]
    check_eq(list(pg.COVERAGE), order, "images in ladder order")
    for tag in order:
        used = {s[0] for s in pg.COVERAGE[tag] if not isinstance(s, str)}
        check(bool(used - seen) or tag in BEHAVIOUR,
              f"{tag}: adds a new instruction or a declared new behaviour")
        seen |= used
    unreached = set(INSTRUCTIONS) - seen
    # RULES, NOT A NAME LIST. At 66 instructions the uncovered set could be
    # enumerated by hand. At 174 a hand list rots on the next addition and
    # stops being read, which is worse than no list -- so every uncovered
    # instruction must match exactly ONE rule below, and each rule says what
    # WOULD cover the family and why nothing does yet.
    #
    # "Uncovered" is not "unproven". Most of these are one microcode row
    # whose decoder output is bench-proven by an image that IS here: LDBS is
    # PUSH's SP->MAR prefix with a different last row, ADI_C is ADI with one
    # DST code changed. What is untested is the ROW, and a wrong row is one
    # burn away from a right one.
    #
    # THE COUNT IS THE TRIPWIRE. Rules alone would silently absorb a new
    # instruction; the count makes every addition a deliberate edit here.
    RULES = [
        (lambda n: n == "NOP",
         "does nothing observable -- there is no OB reading that "
         "distinguishes NOP from the state before it"),
        (lambda n: n.startswith("MOV"),
         "one row over a U28/U30 or U70/U71 decoder pair that PROG_mov and "
         "PROG_sp already drive; the row differs only in which code it names"),
        (lambda n: n.endswith(("_B", "_C")) or n in ("BIT", "CPX", "CMPB", "TST"),
         "an ALU row with a different destination or a different '382 "
         "function code; PROG_alu proves every code and PROG_jnc proves the "
         "NONE destination"),
        (lambda n: n in ("ADI", "SUI", "BSUI", "ANI", "ORI", "XRI", "CPI"),
         "immediate ALU -- LDBI's fetch row followed by an ALU row, and both "
         "halves are separately covered. An image would only re-prove the "
         "TMP_B shadow that PROG_shl already leans on"),
        (lambda n: n.startswith("OUT"),
         "OB latches MDR, so every OUT variant is the SAME strobe over a "
         "source that some other image already drives onto the bus"),
        (lambda n: n.startswith(("PUSH", "POP")),
         "identical shape to PUSHA/POPA, bench-proven by PROG_sp2"),
        (lambda n: n.startswith(("LDSP", "STSP", "STPC", "LXI")),
         "_MARFILL with a pointer half as the source or destination; the "
         "prefix is LDA's verbatim and the codes are PROG_sp's"),
        (lambda n: n.startswith("MVI"),
         "a MAR prefix plus src=ROM dst=RAM. Both halves covered; the new "
         "thing is only that the byte never passes through a register"),
        (lambda n: n.startswith("ST") and n[2:].rstrip("XS") in
                   ("ADD", "SUB", "BSUB", "AND", "OR", "XOR"),
         "a MAR prefix plus an ALU row writing RAM -- PROG_alu proves the "
         "ALU, PROG_mem proves the store, and nothing new sits between them"),
        (lambda n: n in ("LDAS", "STAS", "LDBS", "STBS", "LDCS", "STCS"),
         "SP-relative: PUSH's SP->MAR prefix with a different final row"),
        (lambda n: n in ("LDAX", "STAX", "LDBX", "STBX", "LDCX", "STCX",
                         "JZX", "JCX"),
         "indexed through B:C -- PROG_ptr covers the prefix and both "
         "directions through it"),
        (lambda n: n in ("LDB", "LDC", "STB", "STC"),
         "LDA/STA's _MARFILL prefix with a different register on the last "
         "row; PROG_ptr reaches LDB, which is the one whose readback path "
         "carries the pointer witness"),
        (lambda n: n.endswith("M") and n.startswith(("LD", "ST", "JMP", "JZ", "JC")),
         "MEMORY-INDIRECT. LDAM, STAM and JMPM each have their OWN image "
         "(ind, indst, indj) because this is the only new ADDRESSING MODE, "
         "the only use of the MDR park outside RET, and the only operand "
         "shape that writes an address twice. LDBM, JZM and JCM are the "
         "same eight-row prefix with a different final row"),
        (lambda n: n in ("RST", "INXSP", "DCXSP", "SPHL", "HLSP", "JMPX",
                         "JMPSP", "LDCI"),
         "no (OB, END) fingerprint of its own -- it either restarts the "
         "program, or only moves a pointer, and the ladder matches images by "
         "their answer. Same reason PROG_swdemo is not a coverage image"),
    ]
    unruled, multi = [], []
    for name in sorted(unreached):
        hits = [r for pred, r in RULES if pred(name)]
        if not hits:
            unruled.append(name)
        elif len(hits) > 1:
            multi.append((name, len(hits)))
    check_eq(unruled, [],
             "every uncovered instruction matches a rule that says what "
             "would cover it")
    check_eq(multi, [],
             "no instruction matches two rules -- overlapping rules mean the "
             "reason printed is arbitrary")
    check_eq(len(unreached), 135,
             "the uncovered count is a TRIPWIRE: adding an instruction "
             "without an image is fine, doing it silently is not")


def test_sp_image_gates_phase_b_without_call_ret():
    """PROG_sp is the phase-B bench gate: the SP + RAM round trip proven by
    the push/pop family ALONE. It must land the same answer signature as
    PROG_stack -- 0x27 correct LIFO, 0xD9 names a wrong order -- while never
    executing CALL or RET, because the PC-pushback '245s (U72/U73) are
    phase-C hardware that does not exist yet when this image gates the bench.
    PROG_sp passing while PROG_stack fails localises the fault to phase C."""
    print("the sp image proves the SP without phase-C hardware")
    if "sp" not in pg.COVERAGE:
        check(False, "sp image exists in COVERAGE")
        return
    prog = pg.COVERAGE["sp"]
    used = {s[0] for s in prog if not isinstance(s, str)}
    check_eq(used & {"CALL", "RET"}, set(),
             "no CALL/RET -- phase C hardware stays out of the gate")
    check({"LXISP", "PUSHA", "PUSHB", "POPA", "POPB"} <= used,
          "LXISP and all four push/pop variants present")
    res = pg.simulate(prog)
    check(res["halted"], "sp halts")
    check_eq(res["out"], pg.STACK_EXPECT,
             "OB matches PROG_stack's 0x27/0xD9 signature")


def test_dip_image_takes_its_operand_from_the_card():
    """`dip` is the image whose answer is not fully determined by the ROM --
    since phase E because of an ADDRESS, not because of an instruction. The
    machine reads card zero at 0x4000 with a plain LDA. The image must
    therefore DECLARE the switch setting it expects, or the expectation is
    unfalsifiable -- and it must produce a DIFFERENT answer under a different
    setting, or it is not really reading the card at all."""
    print("the dip image is genuinely driven by SW1, through the bus")
    check("dip" in pg.COVERAGE_SW, "the image declares its SW1 setting")
    sw = pg.COVERAGE_SW["dip"]
    got = pg.simulate(pg.COVERAGE["dip"], switches=sw)
    check_eq(got["out"], pg.EXPECT_SUM,
             f"SW1=0x{sw:02X} reproduces the milestone answer 0x{pg.EXPECT_SUM:02X}")
    # a stuck '244, or a card-zero decode that never selected, would leave A
    # at whatever it held -- the answer must MOVE when the switches move
    other = pg.simulate(pg.COVERAGE["dip"], switches=(sw ^ 0xFF) & 0xFF)
    check(other["out"] != got["out"],
          "flipping every switch changes the answer")
    check_eq(pg.simulate(pg.COVERAGE["dip"], switches=sw)["ends"],
             pg.simulate(pg.PROGRAM)["ends"],
             "same instruction count as the milestone — only the SOURCE moved")


def test_alu_image_hits_every_sa_code():
    print("alu image exercises all 8 SA codes")
    alu_ops = {"ADD", "SUB", "AND", "OR", "XOR", "CLR", "SET", "BSUB"}
    used = {s[0] for s in pg.COVERAGE["alu"] if not isinstance(s, str)}
    check_eq(alu_ops - used, set(), "every ALU mnemonic appears")


def test_mem_image_round_trips_ram():
    print("mem image proves the RAM round-trip and the MAR latch")
    res = pg.simulate(pg.COVERAGE["mem"])
    check(res["ram_writes"] > 0, "image writes RAM")
    check(res["ram_reads"] > 0, "image reads RAM back")
    check_eq(res["out"], res["stored"], "OB is the byte that went to RAM")


def test_flow_image_never_reaches_poison():
    print("flow image jumps over its poison byte")
    res = pg.simulate(pg.COVERAGE["flow"])
    check(not res["hit_poison"], "the JMP skipped the poison HALT")
    check(res["branches_not_taken"] > 0, "a JNZ not-taken arm was exercised")


def test_loop_image_iterates_exactly():
    print("loop image iterates the declared number of times")
    res = pg.simulate(pg.COVERAGE["loop"])
    check(res["branches_taken"] >= 2, "JNZ taken arm exercised repeatedly")
    check_eq(res["out"], pg.LOOP_EXPECT, "accumulator matches the declared total")


def test_milestone_is_a_real_carry_chain():
    """The milestone used to be 5+3=8: one bit set, low nibble only, one
    carry. That cannot see a stuck or swapped bit in the upper nibble, and it
    barely exercises the ripple between the two '382s. The addends must put
    bits in both nibbles and the carry must cross the nibble boundary."""
    print("the milestone addends stress the carry chain")
    a, b, want = pg.ADDEND_A, pg.ADDEND_B, pg.EXPECT_SUM
    check_eq(a + b, want, "the addends actually make the answer")
    check(want < 0x100, "no carry out of bit 7 — that is a flags test, not this")
    for nm, v in (("A", a), ("B", b), ("sum", want)):
        check(v & 0xF0 and v & 0x0F, f"{nm} 0x{v:02X} has bits in BOTH nibbles")
    carries, c, crossed = 0, 0, False
    for i in range(8):
        c = 1 if ((a >> i) & 1) + ((b >> i) & 1) + c > 1 else 0
        carries += c
        if i == 3 and c:
            crossed = True
    check(carries >= 4, f"carry ripples through {carries} positions")
    check(crossed, "the carry CROSSES the nibble boundary at bit 3 -> 4")


def test_diag_triple_ambiguity_is_generated():
    """block2.fetch proves the fetch path reads ROM at PC, PC+1, PC+2 by
    matching three consecutive diag bytes. Those do NOT identify a unique
    address — the byte truncates to 8 bits — so the acceptance threshold must
    be the image's own worst case, generated, never hand-picked. A guessed
    threshold of 4 would false-fail on the 3% of positions that legitimately
    match at 8."""
    print("the diag triple ambiguity is generated, not guessed")
    m = pg.diag_triple_max()
    check(m >= 1, "a worst case exists")
    # recompute independently of the generator's own helper
    seen = {}
    for a in range(pg.ROM_IMAGE - 2):
        k = (pg.diag_byte(a), pg.diag_byte(a + 1), pg.diag_byte(a + 2))
        seen[k] = seen.get(k, 0) + 1
    check_eq(m, max(seen.values()), "matches an independent recount")
    check(m < 32, f"ambiguity {m} still discriminates ~1 in {32768 // m}")
    hdr = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                            "tests", "dino_bringup", "src", "progrom_expect.h")).read()
    check(f"#define PR_DIAG_TRIPLE_MAX {m}u" in hdr,
          "the rig's threshold comes from the header, not from a literal")


def test_images_fit_and_safe_fill():
    print("images fit the ROM and are HALT-filled")
    for tag, prog in pg.COVERAGE.items():
        img = pg.build_image(prog)
        check_eq(len(img), pg.ROM_IMAGE,
                 f"{tag}: image is a full {pg.ROM_IMAGE}B ROM")
        check_eq(img[-1], pg.SAFE_FILL, f"{tag}: tail is the safe HALT fill")
        check(img[0] != pg.DIAG_ZERO, f"{tag}: byte 0 does not collide with DIAG")


def test_sp2_sp3_are_not_blind_to_a_frozen_sp():
    """THE REGRESSION THAT COST 2026-08-24. PROG_sp1 reported 0x2C on a
    machine whose SP had never moved -- push and pop used the same cell, so
    the byte round-tripped perfectly through a stack pointer wired to
    nothing. These two images must FAIL under that fault, and the way to
    prove it is to simulate the fault, not to argue about it."""
    print("sp2/sp3 detect a stack pointer that never moves")

    check_eq(pg.simulate(pg.COVERAGE["sp2"])["out"], pg.STACK_PUSH_B,
             "sp2 healthy answer is 0x53")
    check_eq(pg.simulate(pg.COVERAGE["sp3"])["out"], pg.STACK_PUSH_A,
             "sp3 healthy answer is 0x2C")

    # The blindness is STRUCTURAL, so prove it from the program text rather
    # than by arguing: sp1 pushes and pops at ONE SP value, so its answer
    # cannot depend on SP having moved. sp2 reads a cell only a moved SP
    # reaches, which is the whole difference.
    check_eq(len(_push_cells(pg.COVERAGE["sp1"])), 1,
             "sp1 pushes to ONE stack cell -- that IS its blindness")
    check(len(_push_cells(pg.COVERAGE["sp2"])) > 1,
          "sp2 pushes to more than one cell, so a frozen SP collapses them "
          "and the planted sentinel survives to name the fault")

    # sp3's outcomes must be three DISTINCT bytes or the answer names nothing
    check_eq(len({pg.SP_SENTINEL_AT, pg.SP_SENTINEL_ABOVE, pg.STACK_PUSH_A}), 3,
             "sp3's three outcomes are three distinct bytes")


def _push_cells(prog):
    """The distinct addresses a healthy run's PUSHes land on, walked with
    the empty-descending rule: store at [SP], then decrement."""
    sp, cells = None, set()
    for step in prog:
        if isinstance(step, str):
            continue
        if step[0] == "LXISP":
            sp = step[1] | (step[2] << 8)
        elif step[0] in ("PUSHA", "PUSHB") and sp is not None:
            cells.add(sp)
            sp = (sp - 1) & 0xFFFF
        elif step[0] in ("POPA", "POPB") and sp is not None:
            sp = (sp + 1) & 0xFFFF
    return cells


def test_call_image_makes_the_return_address_the_observable():
    """PROG_stack proves a return HAPPENED. PROG_call proves it landed on
    the RIGHT BYTE, and does it from an address where PC_HI is non-zero so
    a U73 that delivers 0x00 for any reason cannot pass by accident."""
    print("the call image names where RET landed")
    prog = pg.COVERAGE["call"]

    labels = _labels(prog)
    ret_addr = labels["landed"]
    check(ret_addr > 0xFF,
          f"return address 0x{ret_addr:04X} is above 0x00FF, so the pushed "
          f"PC_HI = 0x{ret_addr >> 8:02X} is NON-ZERO and U73 is load-bearing")

    res = pg.simulate(prog)
    check(res["halted"], "call halts")
    check_eq(res["out"], pg.CALL_LANDED, "healthy answer is the landing marker")

    # the poison must run BEFORE the call, or a wrong landing inherits the
    # previous image's OB instead of reporting 0xFF
    first = next(s for s in prog if not isinstance(s, str))
    check_eq(first, ("LDAI", pg.POISON), "OB is poisoned before anything else")
    check(prog.index("landed") > prog.index("high"),
          "the landing marker sits after the CALL, not before it")

    # every byte that is NOT the landing site must be HALT or unreachable,
    # so a wrong landing cannot stumble into the OUT
    body = prog[prog.index("high"):]
    outs = [s for s in body if not isinstance(s, str) and s[0] == "OUT"]
    check_eq(len(outs), 1, "exactly one OUT past the padding")

    check({"CALL", "RET"} <= {s[0] for s in prog if not isinstance(s, str)},
          "the image actually executes CALL and RET")


def test_calladdr_splits_call_from_ret():
    """PROG_call runs CALL and RET together, so a failure lights up five
    pins that have never been asserted and names none. calladdr must run
    CALL and NEVER RET, and must check BOTH pushed bytes separately so a
    wrong one names which half of the address broke."""
    print("calladdr exercises CALL without ever executing RET")
    prog = pg.COVERAGE["calladdr"]
    used = {s[0] for s in prog if not isinstance(s, str)}
    check("CALL" in used, "calladdr executes CALL")
    check_eq(used & {"RET"}, set(), "calladdr NEVER executes RET")

    res = pg.simulate(prog)
    check(res["halted"], "calladdr halts")
    check_eq(res["out"], pg.CALLADDR_OK, "healthy answer is the OK marker")

    # CALL pushes PC+1, NOT PC+3 -- the pushes at T3/T7 precede the operand
    # fetch at T9/T10. RET compensates with PC_UP on T12 and T13. If that
    # convention ever changes, this assertion is what catches it.
    labels = _labels(prog)
    pushed = labels["call_at"] + 1
    check(pushed >> 8 != 0,
          f"pushed address 0x{pushed:04X} has non-zero PC_HI, so U73 is "
          f"load-bearing")
    check_eq(labels["after_call"], labels["call_at"] + 3,
             "a real RET would resume 3 bytes on, not at the pushed address")

    # the three answers must be three distinct, non-rail bytes
    vals = [pg.CALLADDR_OK, pg.CALLADDR_BAD_LO, pg.CALLADDR_BAD_HI]
    check_eq(len(set(vals)), 3, "OK / bad-LO / bad-HI are three distinct bytes")
    for v in vals:
        check(v not in (0x00, 0xFF), f"0x{v:02X} is not a rail")


def test_stack_image_poisons_ob_before_the_call():
    """A RET that lands ONE BYTE LATE hits the HALT after the OUT, so OUT
    never runs and OB keeps whatever the previous image left. PROG_sp --
    the image burned immediately before -- answers 0x27, the same byte
    PROG_stack expects. Without a poison prefix that reads as a pass."""
    print("stack destroys the previous answer before it calls")
    prog = pg.COVERAGE["stack"]
    first = next(s for s in prog if not isinstance(s, str))
    check_eq(first, ("LDAI", pg.POISON),
             "stack poisons OB first -- PROG_sp's 0x27 cannot be inherited")
    idx = [i for i, s in enumerate(prog)
           if not isinstance(s, str) and s[0] == "OUT"]
    call_at = next(i for i, s in enumerate(prog)
                   if not isinstance(s, str) and s[0] == "CALL")
    check(idx[0] < call_at, "the poison OUT runs BEFORE the CALL")
    check_eq(pg.simulate(prog)["out"], pg.STACK_EXPECT,
             "the healthy answer is unchanged at 0x27")


def _labels(prog):
    """Label -> address, using the microcode table's declared lengths."""
    addr, out = 0, {}
    for step in prog:
        if isinstance(step, str):
            out[step] = addr
            continue
        addr += INSTRUCTIONS[step[0]][0]
    return out


def test_swdemo_branches_on_the_bench_and_balances_the_stack():
    """swdemo is the first image whose behaviour changes without a reburn.
    Both arms must be reachable from SW1 bit 0 ALONE, both must be
    stack-driven, and both must leave SP where LXISP put it -- an
    unbalanced arm walks SP down through RAM and scribbles over the delay
    counters within seconds."""
    print("swdemo picks its arm from SW1 bit 0 and balances both stacks")
    fast = pg._build_swdemo(outer_n=1, inner_n=2)

    blink = pg.simulate(fast, max_steps=60000, switches=0x00)["outs"]
    sweep = pg.simulate(fast, max_steps=60000, switches=0x01)["outs"]

    check_eq(blink[:4], [pg.SWDEMO_BLINK_B, pg.SWDEMO_BLINK_A] * 2,
             "bit 0 clear -> 0x55/0xAA interleaved blink")
    check_eq(sweep[:len(pg.CYLON_FRAMES)], list(pg.CYLON_FRAMES),
             "bit 0 set -> the cylon frame sweep")

    # LIFO order is VISIBLE in the blink arm: 0xAA is pushed FIRST and must
    # come back SECOND. A stack that returns pushes in order shows AA then 55.
    check(blink[0] == pg.SWDEMO_BLINK_B,
          "blink shows the LAST byte pushed first -- LIFO, not FIFO")

    # bits 1-7 must be ignored, so the other seven switches stay free
    for sw in (0x02, 0xFE):
        check_eq(pg.simulate(fast, max_steps=20000, switches=sw)["outs"][0],
                 pg.SWDEMO_BLINK_B, f"switches=0x{sw:02X}: bit 0 clear -> blink")
    for sw in (0x03, 0xFF):
        check_eq(pg.simulate(fast, max_steps=20000, switches=sw)["outs"][0],
                 pg.CYLON_FRAMES[0], f"switches=0x{sw:02X}: bit 0 set -> sweep")

    # stack balance, counted from the program text so it holds for the
    # BURNED image and not merely for the fast host variant
    for arm, lo, hi in _swdemo_arms(pg.SWDEMO_PROGRAM):
        pushes = sum(1 for s in pg.SWDEMO_PROGRAM[lo:hi]
                     if not isinstance(s, str) and s[0] in ("PUSHA", "PUSHB"))
        pops = sum(1 for s in pg.SWDEMO_PROGRAM[lo:hi]
                   if not isinstance(s, str) and s[0] in ("POPA", "POPB"))
        check_eq(pushes, pops, f"{arm} arm balances: {pushes} push / {pops} pop")
        check(pushes > 0, f"{arm} arm actually uses the stack")

    check("swdemo" not in pg.COVERAGE,
          "swdemo is NOT a coverage image -- neither arm halts, so it has "
          "no (OB, END) fingerprint for the ladder to match")


def _swdemo_arms(prog):
    """(name, start, end) for each arm, split at the `sweep` label."""
    cut = prog.index("sweep")
    return [("blink", prog.index("top"), cut), ("sweep", cut, len(prog))]


# ---- pytest bridge (Task 8 VPLAN audit, fix round 2) ---------------------
# check()/check_eq()/check_raises() only APPEND to the module-level FAILS
# list -- they never raise on their own, by design: the __main__ block
# below wants to run every check in a test function and print a full
# FAILS summary before exiting, not stop at the first failure. Left
# alone, pytest sees every test_* function return None and reports PASS
# regardless of what landed in FAILS -- confirmed HOLLOW by direct
# mutation: patching progrom_gen.sim_supports() to reject NOP/LDCI left
# `pytest -k test_simulator_against_microcode` reporting `1 passed` while
# `python3 docs/notes/test_progrom_coverage.py` correctly printed FAILED
# and exited 1.
#
# Fixed by wrapping every test_* function so a run UNDER PYTEST raises if
# its OWN execution added anything to FAILS -- the assertion happens
# INSIDE the wrapped call itself (the pytest "call" phase), not in a
# fixture's post-yield teardown, so pytest reports a clean single FAILED
# per test, never a confusing "1 passed" alongside a separate teardown
# ERROR (the first draft of this fix used an autouse fixture and produced
# exactly that confusing split -- caught before committing, replaced with
# this wrapping approach instead).
#
# Guarded by `__name__ != "__main__"` so the direct-invocation path below
# is completely untouched: this loop runs (if at all) BEFORE the
# `if __name__ == "__main__":` block ever builds its own function-
# reference tuple, but only mutates `globals()` when pytest is doing the
# importing (pytest's collection never sets `__name__` to `"__main__"`
# for a collected module) -- a plain `python3
# docs/notes/test_progrom_coverage.py` run calls the UNWRAPPED originals
# and keeps its own collect-everything-then-report-once behavior exactly
# as it always has.
if pytest is not None and __name__ != "__main__":
    def _wrap_for_pytest(fn):
        def _wrapped():
            start = len(FAILS)
            result = fn()
            new = FAILS[start:]
            if new:
                raise AssertionError(
                    f"{len(new)} check() failure(s) in {fn.__name__}:\n"
                    + "\n".join(f"  - {f}" for f in new))
            return result
        _wrapped.__name__ = fn.__name__
        _wrapped.__doc__ = fn.__doc__
        return _wrapped

    for _tname, _tobj in list(globals().items()):
        if _tname.startswith("test_") and callable(_tobj):
            globals()[_tname] = _wrap_for_pytest(_tobj)


if __name__ == "__main__":
    # ENUMERATED, not a hand-written tuple. The tuple that used to live here
    # named 14 of this module's 19 test_ functions; five had never run --
    # including both phase-C witnesses and the swdemo stack-balance check.
    # Adding a name to a list is a step someone has to remember, and this is
    # what forgetting looks like. Guarded by test_suite_reachability.py.
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        _fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\ncoverage ROMs: OK")
