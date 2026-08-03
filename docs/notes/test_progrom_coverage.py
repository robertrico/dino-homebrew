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
        "flow": "unconditional PC_LOAD, and the JNZ NOT-taken arm",
        "loop": "the JNZ TAKEN arm, iterated an exact number of times",
        "mem": "MAR as a LATCH, not just a mux — the named gap in BRINGUP.md",
    }
    seen = set()
    order = ["probe", "adda", "addb", "real", "alu", "mem", "flow", "loop"]
    check_eq(list(pg.COVERAGE), order, "images in ladder order")
    for tag in order:
        used = {s[0] for s in pg.COVERAGE[tag] if not isinstance(s, str)}
        check(bool(used - seen) or tag in BEHAVIOUR,
              f"{tag}: adds a new instruction or a declared new behaviour")
        seen |= used
    unreached = set(INSTRUCTIONS) - seen
    # LDCI is unreachable by design: C is write-only until MOV exists
    check_eq(unreached, {"LDCI", "NOP"},
             "only LDCI (C is write-only) and NOP go unexercised")


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
    for a in range(pg.SIZE - 2):
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
        check_eq(len(img), pg.SIZE, f"{tag}: image is a full {pg.SIZE}B ROM")
        check_eq(img[-1], pg.SAFE_FILL, f"{tag}: tail is the safe HALT fill")
        check(img[0] != pg.DIAG_ZERO, f"{tag}: byte 0 does not collide with DIAG")


if __name__ == "__main__":
    for fn in (test_labels, test_simulator_against_microcode,
               test_flags_hold_across_non_alu, test_images_are_witnesses,
               test_coverage_is_progressive, test_alu_image_hits_every_sa_code,
               test_mem_image_round_trips_ram, test_flow_image_never_reaches_poison,
               test_loop_image_iterates_exactly,
               test_milestone_is_a_real_carry_chain,
               test_diag_triple_ambiguity_is_generated,
               test_images_fit_and_safe_fill):
        fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\ncoverage ROMs: OK")
