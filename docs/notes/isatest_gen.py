#!/usr/bin/env python3
"""PROG_isa — a self-checking test that names the instruction that lied.

    python3 docs/notes/isatest_gen.py            # build, verify, report
    python3 docs/notes/isatest_gen.py --mutate   # prove each subtest is not blind

WHY THIS SHAPE. OB is one byte, so one image per instruction is one burn per
instruction. Instead every instruction gets a SUBTEST: set up known operands,
run it, read the result back into A, compare with CPI, and JNZ to a stub that
does `OUTI <id>; HALT`. Fall off the end of the list and the program OUTs a
pass byte. One burn, one RESET, one number -- either PASS or the id of the
FIRST instruction that misbehaved.

NOT ONE EXPECTED VALUE IS COMPUTED BY HAND. Each subtest is assembled, run
through `progrom_gen.simulate()` -- which interprets the same microcode rows
the machine will execute -- and the answer it produces is what gets baked in.
A hand-computed expectation is a second source of truth and a false bench
failure waiting to happen.

AND THE SUBTESTS ARE THEMSELVES TESTED. `--mutate` corrupts one instruction's
microcode at a time and asserts the program then fails reporting THAT
instruction's id. A subtest that still passes with its instruction broken is
blind and is not counted as coverage. Without that, "174 subtests" is a blind
counter, which is the thing this project keeps learning not to trust.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import microcode_gen as mc                                    # noqa: E402
import progrom_gen as pr                                      # noqa: E402
from progrom_gen import Ref, RAM_BASE                         # noqa: E402

# ---- fixed sentinels ---------------------------------------------------
# Chosen so a swapped operand, a stuck bit or a bit-reversed byte lands on a
# DIFFERENT value: no two are bit-reversals of each other, none is 0x00 or
# 0xFF, and none is a palindrome.
SA, SB, SC = 0x5C, 0x33, 0x71       # A, B, C
SN = 0x47                           # the immediate operand
SM = 0x2E                           # what a memory cell is planted with
PASS = 0xB4                         # > any subtest id, mirror 0x2D

STACK = RAM_BASE + 0x0FF
CELL = RAM_BASE + 0x040
CELL2 = RAM_BASE + 0x041
PTR = RAM_BASE + 0x050              # a pointer, for the indirect mode
FLAG = RAM_BASE + 0x060             # RST's witness


def _a(x):
    return (x & 0xFF, (x >> 8) & 0xFF)


# ---- how each instruction is set up and read back -----------------------
SHAPE_ARGS = {
    "IMPLIED": [], "IMMEDIATE": [SN], "ADDRESS": list(_a(CELL)),
    # THE POINTER IS EMITTED AS ptr THEN ptr+1. Writing _a(PTR) * 2 gives the
    # SAME address twice, so the instruction reads its high byte out of the
    # low byte's cell and follows a pointer built from one byte repeated.
    # asm.py computes ptr+1 for you; building tuple-form steps here bypasses
    # it, and STAM was silently storing into 0x4040 until mutation testing
    # reported its subtest blind.
    "ADDR_IMM": list(_a(CELL)) + [SN],
    "POINTER": list(_a(PTR)) + list(_a(PTR + 1)),
}


def _shape(name):
    import asm
    return {asm.IMPLIED: "IMPLIED", asm.IMMEDIATE: "IMMEDIATE",
            asm.ADDRESS: "ADDRESS", asm.ADDR_IMM: "ADDR_IMM",
            asm.POINTER: "POINTER"}[asm.SHAPE[name]]


def _last(name):
    """(misc, src, dst) of the instruction's final row, as names."""
    rows = mc.INSTRUCTIONS[name][1]
    misc, src, dst = mc._fields(rows[-1])
    inv = lambda d, v: {vv: kk for kk, vv in d.items()}.get(v)   # noqa: E731
    return inv(mc.MISC, misc), inv(mc.SRC, src), inv(mc.DST, dst)


BASE = [("LXISP", *_a(STACK)), ("LDCI", SC), ("LDBI", SB), ("LDAI", SA)]
IDX = [("LDBI", CELL >> 8), ("LDCI", CELL & 0xFF), ("LDAI", SA)]
SPREL = [("LXISP", *_a(CELL)), ("LDCI", SC), ("LDBI", SB), ("LDAI", SA)]
PLANT = [("MVI", *_a(CELL), SM)]
PLANT_PTR = [("MVI", *_a(PTR), CELL & 0xFF),
             ("MVI", *_a(PTR + 1), CELL >> 8),
             ("MVI", *_a(CELL), SM)]

READBACK = {"REG_A": [], "REG_B": [("MOVAB",)], "REG_C": [("MOVAC",)],
            "SP_LO": [("MOVASPL",)], "SP_HI": [("MOVASPH",)]}


# ---- instructions that read the LIVE PC ---------------------------------
# Their result depends on WHERE the subtest sits, so a fixed expected value is
# impossible -- the generator's first attempt compared against a constant and
# the oracle rejected it at MOVAPCL.
#
# The cure is to compare two readings instead of one. The DIFFERENCE between
# two PC reads a known number of bytes apart is the same wherever the subtest
# lands, and it is still a real test: a dead PC readback gives 0x00, a stuck
# one gives 0x00, and both are wrong.
#
# The HIGH halves get no subtest here and the reason is that the difference
# would be 0x00 unless the two reads straddled a page boundary -- and 0x00 is
# what a completely dead readback also produces. An answer that a fault can
# forge is not a witness.
PC_TESTS = {
    "MOVAPCL": [("MOVAPCL",), ("MOVBA",), ("MOVAPCL",), ("SUB",)],
    "MOVBPCL": [("MOVBPCL",), ("MOVAB",), ("MOVBPCL",), ("SUB",)],
    "MOVCPCL": [("MOVCPCL",), ("MOVAC",), ("MOVCPCL",), ("MOVBC",), ("SUB",)],
    "PUSHPCL": [("PUSHPCL",), ("POPA",), ("MOVBA",),
                ("PUSHPCL",), ("POPA",), ("SUB",)],
}
PC_SKIP = {n: "the difference between two reads would be 0x00, which a dead "
              "readback also produces"
           for n in ("MOVAPCH", "MOVBPCH", "MOVCPCH", "PUSHPCH",
                     "STPCL", "STPCH")}


def mode(name):
    """The addressing mode, read off the instruction's own leading rows.

    Every memory-touching instruction opens with one of exactly three
    prefixes, and which one it is decides what the setup has to point at.
    """
    rows = tuple(mc.INSTRUCTIONS[name][1])
    if _shape(name) == "POINTER":
        return "indirect"
    if rows[:2] == tuple(mc._BC_TO_MAR):
        return "indexed"
    if rows[:2] == tuple(mc._SP_TO_MAR):
        return "sprel"
    if rows[:2] == tuple(mc._MARFILL):
        return "absolute"
    misc, src, dst = _last(name)
    return "absolute" if (src == "RAM" or dst == "RAM") else "none"


def body(name):
    """Steps that leave the value under test in A, or None if this
    instruction needs a different kind of witness."""
    misc, src, dst = _last(name)
    shape = _shape(name)
    args = SHAPE_ARGS[shape]
    op = (name, *args)

    if name in PC_TESTS:
        return [("LXISP", *_a(STACK))] + PC_TESTS[name]
    if name in PC_SKIP:
        return None
    if name in ("NOP", "HALT", "RST"):
        return None                              # handled separately
    if misc == "REG_OUT_LOAD":
        return None                              # OB is write-only
    if misc in ("PC_LOAD", "COND") or name == "RET":
        return None                              # a branch: witnessed by land

    # WHICH ADDRESSING MODE, DERIVED FROM THE MICROCODE, NOT THE MNEMONIC.
    # Picking it by name suffix put MVIX -- which is shape IMMEDIATE, not
    # IMPLIED -- on the wrong branch, so B:C was left holding the register
    # sentinels and the store went to 0x3371. The oracle caught it; the
    # generator should not have been able to make the mistake.
    # A POP INCREMENTS BEFORE IT LOADS, and the increment alone moves SP_LO.
    # With SP at 0x80FF the increment takes SP_LO to 0x00 -- which is exactly
    # what a POP that never loaded also leaves there, so the subtest could not
    # tell them apart. Point SP one BELOW a planted cell instead, so a working
    # POP lands on a sentinel and a broken one lands on the cell's own
    # address. Found by mutation testing, not by reading the code.
    if mc.INSTRUCTIONS[name][1][0] == mc.word(misc="SP_UP"):
        return (PLANT + [("LXISP", *_a(CELL - 1)), ("LDCI", SC),
                         ("LDBI", SB), ("LDAI", SA), op]
                + (READBACK[dst] if dst in READBACK else []))

    setup = {"indexed": PLANT + IDX,
             "sprel": PLANT + SPREL,
             "indirect": PLANT_PTR + BASE,
             "absolute": PLANT + BASE,
             "none": list(BASE)}[mode(name)]

    if dst == "RAM":
        # read the cell back ABSOLUTELY -- a readback through the same
        # pointer the store used cannot see a wrong pointer.
        return setup + [op, ("LDA", *_a(CELL))]
    if dst in READBACK:
        return setup + [op] + READBACK[dst]
    if misc in ("SP_UP", "SP_DOWN"):
        return setup + [op, ("MOVASPL",)]
    if dst == "NONE" and src == "ALU":
        return None                              # flag-only: see FLAG_TESTS
    return None


# ---- the flag-only instructions: the witness is the branch --------------
# CMP/CMPB/TST/BIT/CPX/CPI write no destination, so the only thing to observe
# is what the flags make a branch do. Each is run twice, once expecting the
# branch taken and once not: a one-sided branch test is passed by a branch
# wired permanently taken.
FLAG_TESTS = {
    "CMP":  [("LDBI", SB), ("LDAI", SB)],        # A == B -> Z set
    "CMPB": [("LDBI", SB), ("LDAI", SB)],
    "TST":  [("LDAI", 0x00)],                    # A OR A == 0 -> Z set
    "BIT":  [("LDBI", 0x0F), ("LDAI", 0xF0)],    # no bits in common -> Z set
    "CPX":  [("LDBI", SB), ("LDAI", SB)],        # equal -> XOR 0 -> Z set
    "CPI":  [("LDAI", SN)],                      # A == n -> Z set
}
FLAG_ARG = {"CPI": [SN]}


# ---- branch instructions: the witness is where the PC lands -------------
# Each is set up so the branch MUST be taken, and the fall-through path is a
# fail stub. Then, where the instruction is conditional, it is run a second
# time set up so it must NOT be taken -- the fall-through is the pass path
# and the target is the fail stub.
def branch_body(name, tid):
    """(steps, needs_second_direction). Steps end by falling into the next
    subtest when the instruction behaves."""
    tgt, alt = f"t{tid}", f"t{tid}b"
    taken = {                                    # setup that makes Z=0 / C=0
        "JNZ": [("LDBI", 0x01), ("LDAI", 0x02), ("SUB",)],   # 1 != 0 -> Z=0
        "JNC": [("LDBI", 0x20), ("LDAI", 0x10), ("CMP",)],   # A<B -> C=0
        "JZX": [("LDBI", 0x01), ("LDAI", 0x02), ("SUB",)],
        "JCX": [("LDBI", 0x20), ("LDAI", 0x10), ("CMP",)],
        "JZM": [("LDBI", 0x01), ("LDAI", 0x02), ("SUB",)],
        "JCM": [("LDBI", 0x20), ("LDAI", 0x10), ("CMP",)],
    }
    nottaken = {
        "JNZ": [("LDBI", 0x02), ("LDAI", 0x02), ("SUB",)],   # equal -> Z=1
        "JNC": [("LDBI", 0x10), ("LDAI", 0x20), ("CMP",)],   # A>=B -> C=1
        "JZX": [("LDBI", 0x02), ("LDAI", 0x02), ("SUB",)],
        "JCX": [("LDBI", 0x10), ("LDAI", 0x20), ("CMP",)],
        "JZM": [("LDBI", 0x02), ("LDAI", 0x02), ("SUB",)],
        "JCM": [("LDBI", 0x10), ("LDAI", 0x20), ("CMP",)],
    }
    # how the target address is supplied
    if name in ("JMPX", "JZX", "JCX"):
        aim = [("LDBI", 0x00), ("LDCI", 0x00)]   # patched: B:C <- Ref
        via = "bc"
    elif name in ("JMPSP",):
        aim, via = [], "sp"
    elif name in ("JMPM", "JZM", "JCM"):
        aim, via = [], "mem"
    else:
        aim, via = [], "imm"
    return taken.get(name, []), nottaken.get(name, []), aim, via


# ---- assembling one subtest --------------------------------------------
def subtest(name, tid):
    """The steps for one subtest, or None if this instruction is witnessed
    somewhere other than the self-test."""
    b = body(name)
    if b is not None:
        want = expected(b)
        if want is None:
            return None
        return b + [("CPI", want), ("JNZ", Ref(f"f{tid}"))]
    return None


def expected(steps):
    """Run the setup in the oracle and read A. THE ORACLE IS THE ANSWER KEY:
    it interprets the same microcode rows the machine executes, so a value it
    produces cannot disagree with a correct machine."""
    try:
        st = pr.simulate(list(steps) + [("OUT",), ("HALT",)], max_steps=4000)
    except Exception:
        return None
    if not st["halted"] or st["out"] is None:
        return None
    return st["out"]


# ---- branches: the witness is WHERE THE PC LANDS ------------------------
# Every conditional is tested in BOTH directions. A one-sided branch test is
# passed by a branch wired permanently taken, which is exactly what a floating
# select line produces -- the lesson PROG_jnc/PROG_jncswap exist for.
#
# Targets that are not immediate operands are built without any label
# arithmetic: LXISP takes a two-byte operand, so `LXISP Ref(t)` puts a label
# in SP, HLSP moves it to B:C, and MOVASPL/MOVASPH spill it into a RAM
# pointer. That keeps the whole generator in the tuple form the oracle reads.
TAKEN = {                                   # leaves the tested flag CLEAR
    "Z": [("LDBI", 0x01), ("LDAI", 0x02), ("SUB",)],      # 2-1 != 0 -> Z=0
    "C": [("LDBI", 0x20), ("LDAI", 0x10), ("CMP",)],      # A<B      -> C=0
}
NOT_TAKEN = {                               # leaves it SET
    "Z": [("LDBI", 0x02), ("LDAI", 0x02), ("SUB",)],      # equal    -> Z=1
    "C": [("LDBI", 0x10), ("LDAI", 0x20), ("CMP",)],      # A>=B     -> C=1
}
BRANCH_FLAG = {"JNZ": "Z", "JZX": "Z", "JZM": "Z",
               "JNC": "C", "JCX": "C", "JCM": "C"}
SENT_CALL = 0x69                            # what the callee writes to FLAG

# COUNT MODE. The default program stops at the FIRST failing subtest and
# reports its id, which answers "which one" but not "how many" -- and its
# fail stubs are a table of `OUTI n; HALT`, so a wild jump into that table
# reports a plausible subtest number that nothing actually failed.
#
# In count mode every failure instead bumps a RAM counter and execution
# CONTINUES to the next subtest. That is safe because each subtest sets up
# its own registers from scratch. The answer is then the NUMBER of subtests
# that failed, which distinguishes one marginal instruction from scattered
# marginality -- a distinction the first-failure form cannot make.
COUNT_MODE = False
# RECORD MODE. Like count mode -- execution continues past a failure, so a
# wild jump cannot fabricate an answer -- but the cell holds the ID of the
# last subtest that failed rather than a tally. When the count is reliably
# 0 or 1, last-failing IS the-one-failing, and the id is what you actually
# need. 0x00 still means clean, because subtest ids start at 1.
RECORD_MODE = False
# SOAK MODE. Count mode wrapped in an outer loop: the whole 147-subtest
# sequence runs 255 times and every failure accumulates into one counter.
#
# WHY IT EXISTS. At a 1-in-60 failure rate, resetting the machine sixty
# times to see one error is not a measurement -- you cannot tell whether a
# repair helped, and you cannot tell a drifting board from a fixed one.
# 255 passes is ~37,000 subtest executions in about a third of a second,
# so the count is a RATE and a change in it means something.
#
# THE COUNTER MUST SATURATE, NOT WRAP, and the first version did neither.
# It ran 255 passes and simply incremented, so at the observed 1-3 failures
# per pass the byte rolled over two or three times and read 0xFF -- which is
# ALSO the poison byte, so the same value meant "255 failures", "765
# failures" and "never finished". Three meanings, no information.
#
# Now: 64 passes, and the counter stops at 0xFE. 64 passes at the worst rate
# seen (3 per pass) is 192, comfortably inside a byte, and 0xFF is left to
# mean exactly one thing.
#
#     0x00         clean
#     0x01 - 0xFD  the count, and it is a RATE you can compare
#     0xFE         saturated: 254 or more, the machine is broken not marginal
#     0xFF         never reached the final OUT
SOAK_MODE = False
SOAK_PASSES = 64
# PROGRESS MODE. A HANG cannot report anything at the end, because there is
# no end -- so report as you go. Every pass OUTs its own number, and OB is
# left holding the last pass the machine actually reached.
#
# That turns "it usually does not finish" into a MEAN TIME TO FAILURE in
# passes, which is a number that moves when a repair helps. Counting
# miscompares cannot measure a hang; this can.
PROGRESS_MODE = False
# WHERE MODE. Same idea as progress mode, at maximum resolution: OB is
# updated with the SUBTEST ID before each subtest runs, so when the machine
# dies OB names the subtest it died IN rather than the pass it died in.
#
# 147 extra OUTs per pass, about 20% more T-states. Worth it: "died at pass
# 34" is a rate, "died in subtest 91" is a place.
WHERE_MODE = False
ERRS = RAM_BASE + 0x070
PASSES = RAM_BASE + 0x071


def _aim(name, target):
    """Steps that put `target` wherever this branch reads its destination."""
    if name in ("JMP", "JNZ", "JNC", "CALL"):
        return [], (Ref(target),)                     # an immediate operand
    if name in ("JMPX", "JZX", "JCX"):
        # NOT via HLSP. Aiming with HLSP means a broken HLSP sends the jump
        # somewhere arbitrary, and a wild jump is a worse witness than a
        # wrong one -- it can land past the program, halt, and report nothing.
        return [("LXISP", Ref(target)), ("MOVASPL",), ("MOVCA",),
                ("MOVASPH",), ("MOVBA",)], ()
    if name == "JMPSP":
        return [("LXISP", Ref(target))], ()
    if name in ("JMPM", "JZM", "JCM"):
        return [("LXISP", Ref(target)), ("MOVASPL",), ("STA", *_a(PTR)),
                ("MOVASPH",), ("STA", *_a(PTR + 1)),
                ("LXISP", *_a(STACK))], (*_a(PTR), *_a(PTR + 1))
    return None, None


def branch_subtest(name, tid):
    fail, ok, ok2 = f"f{tid}", f"k{tid}", f"k{tid}b"
    if name == "RET":
        return None                                   # covered with CALL
    if name == "CALL":
        # CALL and RET are one subtest: the callee sets a RAM flag, so a CALL
        # that never jumped leaves it clear, and a RET that never returned
        # runs off the end of the callee into a stub that names it.
        return [("MVI", *_a(FLAG), 0x00),
                ("LXISP", *_a(STACK)),
                ("CALL", Ref(f"c{tid}")),
                ("LDA", *_a(FLAG)), ("CPI", SENT_CALL),
                ("JNZ", Ref(fail)),
                ("JMP", Ref(ok)),
                f"c{tid}", ("MVI", *_a(FLAG), SENT_CALL), ("RET",),
                ("OUTI", tid), ("HALT",),             # RET did not return
                ok]
    setup, operand = _aim(name, ok)
    if setup is None:
        return None
    # THE FAILURE PATH MUST NOT USE THE INSTRUCTION UNDER TEST. The first
    # version wrote `JMP Ref(fail)` as the fall-through for every branch --
    # so a broken JMP skipped the test AND its own failure jump, and the
    # subtest passed. Mutation testing found it; reading the code did not.
    # An inline `OUTI id; HALT` cannot be skipped by the thing it is judging.
    stub = ([("JMP", Ref(f"f{tid}"))] if (COUNT_MODE or RECORD_MODE
                                          or SOAK_MODE or PROGRESS_MODE
                                          or WHERE_MODE)
            else [("OUTI", tid), ("HALT",)])
    flag = BRANCH_FLAG.get(name)
    if flag is None:                                  # unconditional
        return ([("LXISP", *_a(STACK))] + setup + [(name, *operand)]
                + stub + [ok])
    aim2, op2 = _aim(name, fail)
    return ([("LXISP", *_a(STACK))] + TAKEN[flag] + setup
            + [(name, *operand)] + stub + [ok]
            + NOT_TAKEN[flag] + aim2 + [(name, *op2)])


# ---- flag-only instructions: the witness is what a branch does ----------
FLAG_ONLY = {
    "CMP":  ([("LDBI", SB), ("LDAI", SB)], [("LDBI", SB), ("LDAI", SC)]),
    "CMPB": ([("LDBI", SB), ("LDAI", SB)], [("LDBI", SB), ("LDAI", SC)]),
    # TST IS `A OR B`, NOT `A OR A`. The ALU's operands are the two shadow
    # latches; there is no path that ORs A with itself. So a zero-test of A
    # alone needs B cleared first, and this subtest does that explicitly
    # rather than relying on whatever B happened to hold.
    "TST":  ([("LDBI", 0x00), ("LDAI", 0x00)],
             [("LDBI", 0x00), ("LDAI", SA)]),
    "BIT":  ([("LDBI", 0x0F), ("LDAI", 0xF0)], [("LDBI", 0x0F), ("LDAI", 0x1F)]),
    "CPX":  ([("LDBI", SB), ("LDAI", SB)], [("LDBI", SB), ("LDAI", SC)]),
    "CPI":  ([("LDAI", SN)], [("LDAI", SA)]),
}
FLAG_OP = {"CPI": (SN,)}


def flagonly_subtest(name, tid):
    zset, zclear = FLAG_ONLY[name]
    op = (name, *FLAG_OP.get(name, ()))
    # Z SET  -> JNZ must NOT branch;  Z CLEAR -> JNZ must branch.
    return (zset + [op, ("JNZ", Ref(f"f{tid}"))]
            + zclear + [op, ("JNZ", Ref(f"k{tid}")), ("JMP", Ref(f"f{tid}")),
                        f"k{tid}"])


# ---- the whole program --------------------------------------------------
def build():
    """(program, {id: mnemonic}, [uncovered]). Subtest ids start at 1 so a
    reading of 0x00 -- a rail -- can never be mistaken for a test number."""
    tests, ids, skipped = [], {}, []
    tid = 0
    for name in sorted(mc.INSTRUCTIONS, key=lambda n: mc.OPCODES[n]):
        cand = tid + 1
        if name in FLAG_ONLY:
            s = flagonly_subtest(name, cand)
        elif name in BRANCH_FLAG or name in ("JMP", "CALL", "RET", "JMPX",
                                             "JMPSP", "JMPM"):
            s = branch_subtest(name, cand)
        else:
            s = subtest(name, cand)
        if s is None:
            skipped.append(name)
            continue
        tid = cand
        ids[tid] = name
        tests.append((tid, name, s))

    # POISON OB FIRST. U35 has no reset and the machine free-runs at
    # power-up, so OB holds the previous program's answer. Without this a
    # test that halts before reaching any OUT -- which is what a wild jump
    # does -- leaves a stale byte on the display that could read as anything,
    # including a pass.
    prog = [("LDAI", pr.POISON), ("OUT",)]
    if RECORD_MODE:
        prog += [("MVI", *_a(ERRS), 0x00)]
        for tid_, name, steps in tests:
            prog += steps                       # ends: CPI want; JNZ f<tid>
            # RECORD THE FIRST FAILURE, NOT THE LAST. Everything before
            # the first is known good, which is the half of the answer a
            # last-failing report throws away -- and when several subtests
            # fail, "last" points at the end of the band rather than its
            # start. Only store if the cell is still clear.
            prog += [("JMP", Ref(f"k{tid_}z")),
                     f"f{tid_}",
                     ("LDA", *_a(ERRS)), ("CPI", 0x00),
                     ("JNZ", Ref(f"k{tid_}z")),      # already recorded
                     ("LDAI", tid_), ("STA", *_a(ERRS)),
                     f"k{tid_}z"]
        prog += [("LDA", *_a(ERRS)), ("OUT",), ("HALT",)]
        return prog, ids, skipped
    if WHERE_MODE:
        prog += [("MVI", *_a(PASSES), 0x00), "outer"]
        for tid_, name, steps in tests:
            prog += [("OUTI", tid_)]             # <-- where we are NOW
            prog += steps
            prog += [("JMP", Ref(f"k{tid_}z")), f"f{tid_}", f"k{tid_}z"]
        prog += [("LDA", *_a(PASSES)), ("INR",), ("STA", *_a(PASSES)),
                 ("CPI", SOAK_PASSES), ("JNZ", Ref("outer"))]
        prog += [("OUTI", PASS), ("HALT",)]
        return prog, ids, skipped
    if PROGRESS_MODE:
        # OB tracks the pass number as it runs. A miscompare is IGNORED
        # here on purpose: this image measures how far the machine gets,
        # not whether it agrees, and mixing the two into one byte is what
        # made the first soak unreadable.
        prog += [("MVI", *_a(PASSES), 0x00), "outer"]
        prog += [("LDA", *_a(PASSES)), ("INR",), ("STA", *_a(PASSES)),
                 ("OUT",)]                       # <-- the progress report
        for tid_, name, steps in tests:
            prog += steps
            prog += [("JMP", Ref(f"k{tid_}z")), f"f{tid_}", f"k{tid_}z"]
        prog += [("LDA", *_a(PASSES)), ("CPI", SOAK_PASSES),
                 ("JNZ", Ref("outer"))]
        prog += [("OUTI", PASS), ("HALT",)]      # 0xB4 = survived them all
        return prog, ids, skipped
    if COUNT_MODE or SOAK_MODE:
        prog += [("MVI", *_a(ERRS), 0x00)]
        if SOAK_MODE:
            prog += [("MVI", *_a(PASSES), SOAK_PASSES), "outer"]
        for tid_, name, steps in tests:
            prog += steps                       # ends: CPI want; JNZ f<tid>
            # saturate at 0xFE rather than wrap past it
            prog += [("JMP", Ref(f"k{tid_}z")),
                     f"f{tid_}",
                     ("LDA", *_a(ERRS)),
                     ("CPI", 0xFE), ("JNZ", Ref(f"b{tid_}")),
                     ("JMP", Ref(f"k{tid_}z")),          # already saturated
                     f"b{tid_}",
                     ("INR",), ("STA", *_a(ERRS)),
                     f"k{tid_}z"]
        if SOAK_MODE:
            prog += [("LDA", *_a(PASSES)), ("DCR",), ("STA", *_a(PASSES)),
                     ("JNZ", Ref("outer"))]
        prog += [("LDA", *_a(ERRS)), ("OUT",), ("HALT",)]
        return prog, ids, skipped
    for tid_, name, steps in tests:
        prog += steps
    prog += [("OUTI", PASS), ("HALT",)]
    for tid_, name, _ in tests:
        prog += [f"f{tid_}", ("OUTI", tid_), ("HALT",)]
    return prog, ids, skipped


def report():
    prog, ids, skipped = build()
    code = pr.assemble(prog)
    st = pr.simulate(prog, max_steps=400000)
    ob = "none" if st["out"] is None else f"0x{st['out']:02X}"
    print(f"PROG_isa: {len(ids)} subtests, {len(code)} bytes, "
          f"OB={ob} halted={st['halted']} steps={st['steps']}")
    if st["out"] != PASS:
        who = ids.get(st["out"], "?")
        print(f"  the generated program does NOT pass its own test: "
              f"OB={ob} names {who}")
    print(f"  not covered here ({len(skipped)}): {', '.join(skipped)}")
    return prog, ids, skipped


def id_map_lines(ids, per_line=6):
    """The bench needs the number on the display translated back into an
    instruction. Generated, so it cannot drift from the program."""
    items = [f"{t:3d} {n:<9}" for t, n in sorted(ids.items())]
    return ["    " + "".join(items[i:i + per_line])
            for i in range(0, len(items), per_line)]


def write():
    prog, ids, skipped = build()
    img = pr.build_image(prog)
    path = os.path.join(pr.ROMS, "PROG_isa.bin")
    open(path, "wb").write(bytes(img))
    return path, pr.crc16(img), ids, skipped


# ---- mutation testing: is any subtest blind? ---------------------------
def _break(w):
    """Remove the final row's effect without changing its length or timing.

    THE FIRST VERSION OF THIS WAS WRONG AND IT FLATTERED THE SUITE. It cleared
    the low three bits to force dst=NONE -- but a BANK-1 destination like
    SP_LO is code 8, whose low three bits are already 000, so the mutation was
    a no-op and fifteen subtests were reported BLIND when the fault was in the
    mutation operator. Clearing the field is not enough; the bank bit has to
    be forced back to bank 0 as well.

    Whichever field carries the instruction's effect is the one removed:
    destination first, then the MISC strobe (a push's effect is SP_DOWN, not
    a destination), then the source.
    """
    misc, src, dst = mc._fields(w)
    if dst != mc.DST["NONE"]:
        return (w & ~0b111) | mc.DST_BANK_N
    if misc != mc.MISC["NONE"]:
        return (w & ~(0b111 << 6)) | mc.MISC_BANK_N
    return (w & ~(0b111 << 3)) | mc.SRC_BANK_N


def mutate():
    """Break one instruction at a time and check the program notices.

    The mutation is realistic rather than violent: the final row's
    DESTINATION is removed, which leaves the byte length and the PC_UP count
    untouched -- so the program still decodes -- but the instruction stops
    delivering its result. That is what a wrong microcode row looks like from
    the outside, and it is what a bad burn looks like.

    Three outcomes, and the difference between the last two matters:
      NAMED     the program fails reporting THAT instruction's own id
      DETECTED  it fails, but reports an earlier subtest that also uses it
      BLIND     it still passes. The subtest proves nothing.
    """
    prog, ids, skipped = build()
    byname = {v: k for k, v in ids.items()}
    named, detected, blind, silent = [], [], [], []
    for name, tid in sorted(byname.items(), key=lambda kv: kv[1]):
        nbytes, rows = mc.INSTRUCTIONS[name]
        broken = list(rows[:-1]) + [_break(rows[-1])]
        mc.INSTRUCTIONS[name] = (nbytes, broken)
        try:
            st = pr.simulate(prog, max_steps=400000)
            ob = st["out"]
        except Exception:
            ob = None
        finally:
            mc.INSTRUCTIONS[name] = (nbytes, rows)
        if ob == PASS:
            blind.append(name)
        elif ob is None or ob == pr.POISON:
            silent.append(name)          # detected, but names nothing
        elif ob == tid:
            named.append(name)
        else:
            detected.append((name, ids.get(ob, hex(ob))))
    print(f"mutation: {len(named)} named, {len(detected)} detected via an "
          f"earlier subtest, {len(silent)} detected but unnamed, "
          f"{len(blind)} BLIND")
    if silent:
        print(f"  unnamed (halts on the poison byte): {', '.join(silent)}")
    if blind:
        print(f"  BLIND -- these subtests prove nothing: {', '.join(blind)}")
    if detected:
        s = ", ".join(f"{a}->{b}" for a, b in detected[:12])
        print(f"  detected but not self-naming: {s}"
              + (" ..." if len(detected) > 12 else ""))
    return named, detected, blind, silent


if __name__ == "__main__":
    report()
    if "--mutate" in sys.argv:
        mutate()
    if "--write" in sys.argv:
        path, crc, ids, _ = write()
        print(f"  wrote {path}  crc={crc:#06x}")
        globals()["COUNT_MODE"] = True
        prog, ids2, _ = build()
        img = pr.build_image(prog)
        p2 = os.path.join(pr.ROMS, "PROG_isacount.bin")
        open(p2, "wb").write(bytes(img))
        st = pr.simulate(prog, max_steps=800000)
        print(f"  wrote {p2}  crc={pr.crc16(img):#06x}  "
              f"oracle OB={st['out']:#04x}")
        globals()["COUNT_MODE"] = False
        globals()["RECORD_MODE"] = True
        prog, _, _ = build()
        img = pr.build_image(prog)
        p3 = os.path.join(pr.ROMS, "PROG_isaid.bin")
        open(p3, "wb").write(bytes(img))
        st = pr.simulate(prog, max_steps=800000)
        print(f"  wrote {p3}  crc={pr.crc16(img):#06x}  "
              f"oracle OB={st['out']:#04x}")
        globals()["RECORD_MODE"] = False
        globals()["SOAK_MODE"] = True
        prog, _, _ = build()
        img = pr.build_image(prog)
        p4 = os.path.join(pr.ROMS, "PROG_isasoak.bin")
        open(p4, "wb").write(bytes(img))
        st = pr.simulate(prog, max_steps=2000000)
        print(f"  wrote {p4}  crc={pr.crc16(img):#06x}  "
              f"oracle OB={st['out']:#04x}  steps={st['steps']}")
        globals()["SOAK_MODE"] = False
        globals()["PROGRESS_MODE"] = True
        prog, _, _ = build()
        img = pr.build_image(prog)
        p5 = os.path.join(pr.ROMS, "PROG_isalive.bin")
        open(p5, "wb").write(bytes(img))
        st = pr.simulate(prog, max_steps=2000000)
        print(f"  wrote {p5}  crc={pr.crc16(img):#06x}  "
              f"oracle OB={st['out']:#04x}  steps={st['steps']}")
        globals()["PROGRESS_MODE"] = False
        globals()["WHERE_MODE"] = True
        prog, _, _ = build()
        img = pr.build_image(prog)
        p6 = os.path.join(pr.ROMS, "PROG_isawhere.bin")
        open(p6, "wb").write(bytes(img))
        st = pr.simulate(prog, max_steps=3000000)
        print(f"  wrote {p6}  crc={pr.crc16(img):#06x}  "
              f"oracle OB={st['out']:#04x}  steps={st['steps']}")
        globals()["WHERE_MODE"] = False
    if "--map" in sys.argv:
        _, ids, _ = build()
        print("\n  the number on OB names the instruction:")
        for line in id_map_lines(ids):
            print(line)