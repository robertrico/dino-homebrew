import math
import os
import sys

import cocotb

# Whole-core coverage ladder (Task 12) -- same dino_core elaboration
# Task 11's test_core_milestone.py already builds (all nine gen/ sheet
# entities + dino_core.vhd's own raw ttl_* gates), a different ROM image
# per run. The milestone (LDAI/ADD/OUT/HALT) and IN prove the machine
# EXECUTES; these prove it executes the WHOLE of the burned-but-never-run
# ISA -- LDA/STA/JMP/JNZ and the seven non-ADD SA codes -- for the first
# time anywhere, bench or sim. progrom_gen.py's own coverage-ladder
# comment (docs/notes/progrom_gen.py:341-350) names the earliest BLOCK
# each image could run at on the real bench; this sim run is the first
# time any of them actually executed against the generated netlist.
#
# RESOLVED FINDING (2026-08-09, task-12-report.md "Findings" section):
# flow_takes_the_jump_and_falls_through and loop_takes_the_jnz_branch
# both FAILED on first run -- JNZ misread FLAG_Z immediately after SUB.
# Root cause was a sim-model tick-count mismatch, NOT a wiring/netlist
# bug (netlist-verified clean, kicad_netlist.build_report('dino_v0_0_2/
# alu.kicad_sch'), CLAUDE.md rule 5) and NOT a real hardware hazard
# (U49's own clock has ~zero extra gate delay off U27's Q-bar; the
# corrupting path needs ~4 real chip delays, tens of ns, against a ~5ns
# hold-time requirement -- comfortable margin, sound synchronous
# design): ttl_74ls373.vhd's own edge/level detector (TMP_A/TMP_B, U45/
# U46) commits 2 clk_sys ticks after its LE transition, but
# ttl_74ls273.vhd's OWN CP-rising detector (FLAG_Z's register, U49) fired
# a stage LATER -- 3 ticks, not 2 -- so it sampled its D-input (the ALU's
# zero-detect, downstream of TMP_A/TMP_B through the U48 mux) AFTER the
# '373 had already restamped and corrupted it. Fixed in
# fpga/ttl/ttl_74ls273.vhd (aligned its detect stage to the SAME
# cp_m(0)/cp_m(1) pair '373 uses) -- see that file's own header for the
# full derivation and fpga/ttl/test_stateful.py's
# register273_captures_pre_edge_d for the isolated regression (RED
# against the pre-fix model, GREEN after). alu/mem/adda/addb never read
# FLAG_Z (no JNZ), so they were never affected either way.
#
# Run via fpga/sim/Makefile's MODULE_UNDER_TEST=dino_core branch, same as
# test_core_milestone.py, with MODULE overridden to point cocotb at THIS
# file (the Makefile's own new seam) and DINO_PROG_HEX pointed at the
# matching hex/PROG_<tag>.hex -- one `make` invocation per tag, a GHDL
# generic is fixed for the whole elaboration (conftest_helpers.
# run_program()'s own docstring explains why):
#
#   make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
#        TESTCASE=alu_covers_every_sa_code  DINO_PROG_HEX=hex/PROG_alu.hex
#   make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
#        TESTCASE=mem_witnesses_mar_as_a_latch DINO_PROG_HEX=hex/PROG_mem.hex
#   make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
#        TESTCASE=flow_takes_the_jump_and_falls_through \
#        DINO_PROG_HEX=hex/PROG_flow.hex
#   make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
#        TESTCASE=loop_takes_the_jnz_branch DINO_PROG_HEX=hex/PROG_loop.hex
#   make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
#        TESTCASE=adda_isolates_tmp_a DINO_PROG_HEX=hex/PROG_adda.hex
#   make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
#        TESTCASE=addb_isolates_tmp_b DINO_PROG_HEX=hex/PROG_addb.hex
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest_helpers import (  # noqa: E402
    CLK_SYS_PERIOD_NS, Y1_DIVIDE, _track_ob, invariant_monitor,
    oracle_final_ob, run_program,
)

HERE = os.path.dirname(os.path.abspath(__file__))
HEX_DIR = os.path.join(HERE, "hex")
DOCS_NOTES = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "notes"))
sys.path.insert(0, DOCS_NOTES)
import progrom_gen                     # noqa: E402
from microcode_gen import INSTRUCTIONS  # noqa: E402


# ---- Job 1: enumerate runnable tags (COVERAGE ^ sim_supports) --------
# The brief's own target set: alu/mem/flow/loop (the four burned-but-
# never-run coverage images CLAUDE.md names) plus adda/addb IF the
# interpreter can execute every opcode they assemble into. Computed here,
# not assumed -- a tag whose program uses an opcode/microcode row the
# interpreter has no model for (progrom_gen.sim_supports()) would make
# oracle_final_ob() raise deep inside simulate(), not fail cleanly at
# collection; enumerating up front turns that into a named, up-front
# fact instead of a buried traceback. "probe"/"real"/"in" are in
# COVERAGE too but are out of this file's scope (real/in already run by
# test_core_milestone.py; probe is not named in the brief's target set).
#
# mardisc/pads added 2026-08-08 (fpga bring-up doc task, merge-driven):
# both are progrom_gen.COVERAGE members that ran green on the bench
# 2026-08-04 (CLAUDE.md's "THE WHOLE ISA HAS EXECUTED" section) but had
# never run in sim against the generated netlist before this file grew
# their two @cocotb.test()s below. Both check _tag_supported() True
# (verified: mardisc uses LDA/LDAI/OUT/STA/HALT, pads uses
# HALT/JMP/LDAI/OUT, all sim_supports()-clean) so they belong in
# _TARGET_TAGS rather than being silently excluded like probe/real/in.
# stack added 2026-08-10 -- the ONLY image that reaches LXISP, PUSH, POP,
# CALL, RET, either SRC/DST bank-1 code, or the third EEPROM's two wired
# bits. Unlike every tag above it, this one has never run on the bench:
# the rig is detached and the hardware is schematic-only, so this test is
# the first and currently the only execution of the stack anywhere.
_TARGET_TAGS = ("alu", "mem", "flow", "loop", "adda", "addb",
                "mardisc", "pads", "stack")


def _tag_supported(tag):
    if tag not in progrom_gen.COVERAGE:
        return False
    names = {step[0] for step in progrom_gen.COVERAGE[tag]
              if not isinstance(step, str)}
    return all(progrom_gen.sim_supports(n) for n in names)


RUNNABLE_TAGS = tuple(t for t in _TARGET_TAGS if _tag_supported(t))
assert RUNNABLE_TAGS == _TARGET_TAGS, (
    f"COVERAGE {{tag: sim_supports}} enumeration for {_TARGET_TAGS} -> "
    f"only {RUNNABLE_TAGS} runnable -- one of alu/mem/flow/loop/adda/addb/"
    f"mardisc/pads "
    f"now uses an opcode/microcode row the interpreter (progrom_gen."
    f"sim_supports()) has no model for; every @cocotb.test() below "
    f"assumes all eight are runnable, so this needs resolving before "
    f"trusting any of them")


# ---- switches trap (Task 11 review, ledgered) ------------------------
# run_program() drives dip_sw AFTER power_on() has already forced it to 0;
# rerun() drives it BEFORE _arm_reset(). An image whose answer depends on
# switches read DURING/before the arming window would see the wrong
# value under one call path or the other. progrom_gen.py's own
# COVERAGE_SW dict (its single source of truth for "which images need a
# switch setting") names exactly one: "in" -- not a member of this file's
# tag list. None of alu/mem/flow/loop/adda/addb execute an IN instruction
# (confirmed below, not assumed) -- switches.value is therefore never
# read by hardware for any image this file runs, so the ordering trap
# does not apply here. Asserted, not just claimed in a comment: a future
# COVERAGE edit that adds a switch-dependent image under one of THESE
# tags fails this assertion loudly instead of silently reading garbage.
for _tag in RUNNABLE_TAGS:
    _names = {step[0] for step in progrom_gen.COVERAGE[_tag]
              if not isinstance(step, str)}
    assert "IN" not in _names, (
        f"COVERAGE[{_tag!r}] now executes IN -- the switches-ordering "
        f"trap (Task 11 review) applies to this image and this file's "
        f"run_program()/oracle calls (switches=0x00 always) need "
        f"re-auditing before trusting its OB")
    assert _tag not in progrom_gen.COVERAGE_SW, (
        f"COVERAGE_SW now lists {_tag!r} -- this tag's answer depends on "
        f"switches; this file's flat switches=0x00 calls are wrong")


# ---- max_us: derived from simulate()'s own step count, not guessed ----
# Machine CLK period, derived from the SAME divider chain conftest_helpers.
# _drive_clk4m_y1() models and fpga/gen/dino_core.vhd actually wires:
# clk4m_y1 (period = Y1_DIVIDE * CLK_SYS_PERIOD_NS) feeds U20 (74LS163),
# whose q0 output toggles once per TWO clk4m_y1 edges (net_u20_q0); U27
# (a 74LS74 wired d1<=n_clk, clk1<=net_u20_q0, q1=>clk -- a toggle flip-
# flop) halves it again -- clk = clk4m_y1 / 4. Cross-checked against Task
# 11's own recorded milestone run (task-11-report.md): 7 instructions x
# (1 T0-fetch T-state + up to 1 microcode-row T-state each, from
# microcode_gen.INSTRUCTIONS) = 14 T-states, observed HALT at 14,230ns ->
# ~1016ns/T-state, matching this derivation's 1000ns to within the
# _arm_reset() polling overhead.
CLK_PERIOD_NS = 4 * Y1_DIVIDE * CLK_SYS_PERIOD_NS      # 4*25*10 = 1000ns

# The worst-case microcode-row count any ONE instruction can take
# (LDA/STA/JMP/JNZ, the three MAR-consuming rows) -- read off the burned
# microcode table itself (microcode_gen.INSTRUCTIONS), not hand-picked.
MAX_ROWS_PER_INSTR = max(len(rows) for _len, rows in INSTRUCTIONS.values())

RESET_OVERHEAD_NS = 2000       # generous vs. Task 11's observed ~230ns
SAFETY_FACTOR = 3              # this is an UPPER bound for wait_halt()'s
                                # timeout, not a tuned value -- a run that
                                # halts sooner just returns early (see
                                # wait_halt()'s own loop), so headroom
                                # here costs nothing on a passing run.


def _max_us_for(tag):
    """wait_halt() timeout, sized from progrom_gen.simulate()'s own
    dynamic `steps` count for this tag -- one FETCH per instruction
    ACTUALLY retired, including every iteration a taken branch (the
    `loop` image's JNZ) really executes, not the program's static
    listing length. Never a flat hand-picked constant like the milestone
    test's MAX_US=500 -- this task's own interface note."""
    steps = progrom_gen.simulate(
        progrom_gen.COVERAGE[tag],
        switches=progrom_gen.COVERAGE_SW.get(tag, 0x00))["steps"]
    t_states = steps * (1 + MAX_ROWS_PER_INSTR)
    ns = RESET_OVERHEAD_NS + t_states * CLK_PERIOD_NS
    return int(math.ceil(ns * SAFETY_FACTOR / 1000))


def _report_monitor():
    cov = getattr(invariant_monitor, "coverage", [])
    excluded = getattr(invariant_monitor, "excluded", [])
    gaps = getattr(invariant_monitor, "gaps", [])
    cocotb.log.info(
        f"invariant monitor: {len(cov)} nets checked, {len(excluded)} "
        f"resolved-but-excluded, {len(gaps)} gap(s)")
    for name in cov:
        cocotb.log.info(f"  checked: {name}")
    for name in excluded:
        cocotb.log.info(f"  excluded (netlist-verified, see "
                         f"conftest_helpers.MONITOR_EXCLUDE): {name}")
    for name, why in gaps:
        cocotb.log.warning(f"  GAP: {name} -- {why}")
    assert not gaps, (
        f"invariant monitor has {len(gaps)} unresolved gated-clock "
        f"identifier(s) from fpga/gen/gated_clocks.txt: "
        f"{[name for name, _ in gaps]} -- a gap means the monitor never "
        f"checked that net this run, so a clean violations list would be "
        f"silently incomplete, not a real pass")


def _report_ob_trace():
    trace = getattr(_track_ob, "trace", [])
    for t_ns, v in trace:
        cocotb.log.info(f"  OB trace: t={t_ns}ns OB=0x{v:02X}")


def _assert_no_violations():
    """Liveness self-check FIRST (Task 11 self-review finding, reused
    verbatim per this task's own interface note): '0 violations' is
    meaningless if the monitor never actually got a qualifying sample to
    check."""
    qualifying = getattr(invariant_monitor, "qualifying_samples", 0)
    assert qualifying > 0, (
        "invariant monitor never saw a single qualifying CLK-high sample "
        "(clk_prev==1 and clk_now==1) this run -- '0 violations' below "
        "would be vacuous, not a real pass")
    cocotb.log.info(f"invariant monitor: {qualifying} qualifying CLK-high "
                     f"samples checked")
    violations = getattr(invariant_monitor, "violations", [])
    assert not violations, (
        f"{len(violations)} standing-invariant violation(s):\n" +
        "\n".join(violations))


async def _run_tag(dut, tag):
    """Shared body every test below calls: run this tag's already-
    elaborated ROM image to HALT, report monitor coverage + OB
    trajectory, assert liveness/no-violations, and return (ob, exp) for
    the caller's own oracle assertion (kept in the caller, not here, so
    each test's docstring sits next to the assertion it documents)."""
    prog_hex = os.path.join(HEX_DIR, f"PROG_{tag}.hex")
    exp = oracle_final_ob(tag, switches=progrom_gen.COVERAGE_SW.get(tag, 0x00))
    ob = await run_program(dut, prog_hex, switches=0x00,
                            max_us=_max_us_for(tag))
    _report_monitor()
    _report_ob_trace()
    _assert_no_violations()
    return ob, exp


@cocotb.test()
async def alu_covers_every_sa_code(dut):
    """docs/notes/progrom_gen.py's ALU_PROGRAM -- every one of the eight
    burned SA codes (XOR, OR, AND, ADD, SUB, BSUB, SET, CLR), CHAINED so a
    wrong code corrupts the final signature instead of being masked by a
    later operation. Only ADD has ever executed on this machine before
    (the milestone) -- this is the first time XOR/OR/AND/SUB/BSUB/SET/CLR
    have executed anywhere, bench or sim. Oracle: progrom_gen.simulate(),
    never hand-typed.
    """
    ob, exp = await _run_tag(dut, "alu")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('alu'), never hand-typed)")


@cocotb.test()
async def mem_witnesses_mar_as_a_latch(dut):
    """docs/notes/progrom_gen.py's MEM_PROGRAM -- store then load-back
    through RAM (STA then LDA). LDA/STA are the ONLY instructions that
    load MAR from a ROM operand and hold it across a later RAM cycle
    (every other instruction leaves MAR untouched); the milestone program
    contains neither, so THIS is the only witness in the whole coverage
    ladder that MAR actually behaves as a LATCH (write MAR_LO/MAR_HI once,
    read it back correctly on the STA's own RAM write and again on the
    LDA's RAM read) rather than merely as a pass-through combinational
    path -- CLAUDE.md's own named gap ('mem is the only witness for
    MAR-as-a-latch, which the milestone never exercises'). A clobbering
    LDAI 0x00 sits between the STA and the LDA specifically so the
    read-back is a real read, not a register that was never actually
    disturbed. Oracle: progrom_gen.simulate(), never hand-typed.
    """
    ob, exp = await _run_tag(dut, "mem")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('mem'), never hand-typed)")


@cocotb.test()
async def flow_takes_the_jump_and_falls_through(dut):
    """docs/notes/progrom_gen.py's FLOW_PROGRAM -- a JMP that must skip a
    poisoned byte (landing on it instead of jumping over it would HALT
    immediately on the wrong path, not silently pass), then a JNZ whose
    condition is FALSE (SUB producing a zero result) and so must NOT be
    taken. This is the first sim run of JMP and of the JNZ NOT-TAKEN arm
    against the generated netlist; the milestone contains neither
    instruction. The JNZ TAKEN arm needs a real ALU flag under a real
    branch, which is what the `loop` image below covers instead (per
    progrom_gen.py's own coverage-ladder comment: block 3 can only prove
    JMP + JNZ-not-taken, since FLAG_Z is strapped high there). Oracle:
    progrom_gen.simulate(), never hand-typed.

    Originally FAILED (OB=0xE7, the "bad"-label value): FLAG_Z's own
    capture (ttl_74ls273.vhd, U49) fired one clk_sys tick later than a
    co-committing '373 (TMP_A/TMP_B, U45/U46) restamps its own output,
    so it sampled the ALU's zero-detect AFTER that restamp had already
    corrupted it. Fixed by aligning the '273 detect stage to '373's own
    (this file's header comment has the full mechanism); see
    task-12-report.md for the trace and fpga/ttl/test_stateful.py's
    register273_captures_pre_edge_d for the isolated regression.
    """
    ob, exp = await _run_tag(dut, "flow")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('flow'), never hand-typed)")


@cocotb.test()
async def loop_takes_the_jnz_branch(dut):
    """docs/notes/progrom_gen.py's LOOP_PROGRAM -- the JNZ TAKEN arm,
    iterating an exact number of times (LOOP_N=3) with the counter and
    accumulator both round-tripped through RAM every pass (no spare
    register exists to hold them). A wrong iteration count changes the
    accumulator's final value, so a correct OB proves the COUNT, not
    merely that the loop eventually exited. This is the longest image in
    the ladder (34 dynamic instruction retirements, the ONLY coverage
    image whose real execution trace is longer than its static program
    listing, precisely because the branch is actually taken more than
    once) and the first time this machine has ever taken a conditional
    branch backward. Oracle: progrom_gen.simulate(), never hand-typed --
    the oracle interprets the SAME microcode-driven branch logic the
    hardware does, so a wrong iteration count in either would show up as
    a self-consistent but wrong number, not a mismatch; PROG_loop's
    generation is exercised by docs/notes/test_progrom_gen.py, out of
    this task's file scope, not re-verified here.

    Originally FAILED one iteration early (OB=0x0E, 2x7 not 3x7) -- the
    same FLAG_Z-capture tick-count mismatch named in
    flow_takes_the_jump_and_falls_through's own docstring (this file's
    header comment has the full mechanism), fixed the same way
    (ttl_74ls273.vhd's detect stage realigned to '373's own).
    """
    ob, exp = await _run_tag(dut, "loop")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('loop'), never hand-typed)")


@cocotb.test()
async def adda_isolates_tmp_a(dut):
    """docs/notes/progrom_gen.py's ADDA_PROGRAM -- adds a known value to
    ZERO with the value carried on the A/TMP_A side (LDAI value; LDBI 0;
    ADD), so the answer IS the operand and a wrong result points squarely
    at the TMP_A shadow latch rather than at the sum path generally. Runs
    under this file because every opcode ADDA_PROGRAM assembles into
    (LDAI, LDBI, ADD, OUT, HALT) resolves against the interpreter
    (progrom_gen.sim_supports(), checked at import time -- this task's
    own enumeration step, RUNNABLE_TAGS). Oracle: progrom_gen.simulate(),
    never hand-typed.
    """
    ob, exp = await _run_tag(dut, "adda")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('adda'), never hand-typed)")


@cocotb.test()
async def addb_isolates_tmp_b(dut):
    """docs/notes/progrom_gen.py's ADDB_PROGRAM -- the same isolation as
    `adda` above, but with the known value carried on the B/TMP_B side
    (LDAI 0; LDBI value; ADD) instead. adda+addb together read as a
    two-bit answer: a bad TMP_A, a bad TMP_B, and a bad shared result path
    each produce a DIFFERENT pair of (adda, addb) outcomes, which a sum
    alone cannot distinguish. Oracle: progrom_gen.simulate(), never
    hand-typed.
    """
    ob, exp = await _run_tag(dut, "addb")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('addb'), never hand-typed)")


@cocotb.test()
async def mardisc_discriminates_mar_lo(dut):
    """docs/notes/progrom_gen.py's MARDISC_PROGRAM -- two STAs to
    addresses that differ ONLY in MAR_LO (0x8004 vs 0x8010), then an LDA
    reading back the FIRST one. This is the image that answered the
    2026-08-04 MAR_LO investigation on the real bench (CLAUDE.md: 'A
    COPPER wire is driven by no test and sampled by no test' -- the
    board-to-board MAR_LO run PROG_mem's own write-then-read-through-one-
    address structure is structurally blind to) and CLAUDE.md's own
    doctrine names it: run BEFORE `loop` in any coverage run order,
    because mem is address-blind and mardisc asks what mem can't. First
    time this image runs against the generated netlist (bench-only until
    now, per progrom_gen.py's own MARDISC_PROGRAM header comment). Oracle:
    progrom_gen.simulate(), never hand-typed -- OB=0x6B means MAR_LO kept
    the two cells distinct, OB=0x2D would mean they collapsed to one.
    """
    ob, exp = await _run_tag(dut, "mardisc")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('mardisc'), never hand-typed)")


@cocotb.test()
async def pads_lands_the_jmp_at_the_named_pad(dut):
    """docs/notes/progrom_gen.py's PADS_PROGRAM -- a JMP to a landing-pad
    grid where every 4-byte slot self-names (LDAI <own address>; OUT;
    HALT), so OB reports the address the PC actually loaded rather than
    merely proving SOME jump happened. Fall-through trap at 0x0006/0x0007
    catches a JMP that failed to load PC at all (OB would stay at the
    leading POISON, 0xFF, not a pad value) -- progrom_gen.py's own header
    comment. Only meaningful once mardisc has confirmed MAR_LO is healthy
    (this file's own mardisc_discriminates_mar_lo, run first per
    CLAUDE.md's ordering doctrine), because pads measures the SAME
    PC_LOAD path one level downstream (M -> U11/U12 -> PCD -> the '193
    parallel load) that a stuck MAR_LO would also corrupt. First time
    this image runs against the generated netlist. Oracle:
    progrom_gen.simulate(), never hand-typed.
    """
    ob, exp = await _run_tag(dut, "pads")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('pads'), never hand-typed)")


@cocotb.test()
async def stack_round_trips_through_lifo_and_returns(dut):
    """docs/notes/progrom_gen.py's STACK_PROGRAM -- the witness for the whole
    2026-08-10 addition: LXISP, PUSHA/PUSHB, POPA/POPB, CALL, RET, both
    SRC/DST bank-1 code groups, and the third EEPROM's ~{SRC_BANK} /
    ~{DST_BANK} bits. Nothing else in the coverage set touches any of them.

    ONE observable, and it is load-bearing. The image's single OUT sits
    AFTER the RET and reports a value computed INSIDE the subroutine, so
    reaching it proves the return address was pushed as two bytes, stored
    to RAM through MAR, popped back, reassembled, and loaded into the PC.
    An earlier OUT would have let a broken CALL/RET leave a correct-looking
    number in OB.

    The value proves ORDER, not merely survival: two DIFFERENT bytes go in
    and come back into SWAPPED registers, and the subroutine SUBTRACTS.
        correct LIFO   0x53 - 0x2C = 0x27
        wrong order    0x2C - 0x53 = 0xD9
    A sum would be order-independent and would pass with the bytes reversed.
    That distinction matters because a crossed ~TC cascade, a stuck U/~D
    direction pin, and a nibble-reversed '245 readback are all live failure
    modes here, and all three survive a one-value round trip unchanged.

    SP starts POISONED in both the oracle (progrom_gen.SP_POISON) and the
    '169 model (ttl_74ls169.vhd's por_value): the real part has no clear and
    comes up random, so a model or oracle starting at zero would be kinder
    than the hardware and would hide a missing LXISP.

    Oracle: progrom_gen.simulate(), never hand-typed.
    """
    ob, exp = await _run_tag(dut, "stack")
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('stack'), never hand-typed). 0xD9 would mean the "
        f"pops came back in the wrong order; no OUT at all means CALL/RET "
        f"never returned")
