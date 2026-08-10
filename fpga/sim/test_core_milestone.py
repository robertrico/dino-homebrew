import os
import sys

import cocotb

# Whole-core testbench (Task 11) -- dino_core, the composed machine (all
# nine gen/ sheet entities + dino_core's own raw ttl_* gates), not one
# sheet. This is the plan's stated "SA-field moment" for the FPGA port:
# the first time the burned microcode ENCODING (docs/notes/microcode_gen.py)
# meets the GENERATED netlist WIRING (fpga/gen/*.vhd, Task 8's emit())
# end-to-end, executing a real program instead of comparing tables against
# each other. CLAUDE.md's own history: the SA-field bit-reversal bug
# (ADD executing as AND) survived every earlier test because every
# earlier test was a permutation check -- nothing compared the encoding
# against the wiring until a program ran. This file is that run, ported.
#
# Run via fpga/sim/Makefile's MODULE_UNDER_TEST=dino_core branch (all
# nine gen/ sheets analyzed + dino_core.vhd last, generics pointed at
# fpga/sim/hex/*.hex, --max-stack-alloc=1024 for the two 32K memory
# models). Two separate `make` invocations, one per ROM image (a GHDL
# generic is fixed for the whole elaboration -- see conftest_helpers.
# run_program()'s own docstring for why):
#
#   make MODULE_UNDER_TEST=dino_core TESTCASE=milestone_free_runs_to_4d
#   make MODULE_UNDER_TEST=dino_core TESTCASE=in_tracks_switches \
#        DINO_PROG_HEX=hex/PROG_in.hex
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest_helpers import (  # noqa: E402
    _track_ob, invariant_monitor, oracle_final_ob, rerun, run_program,
)

HEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hex")
MAX_US = 500


def _report_monitor():
    """Print the standing invariant monitor's coverage/gap list -- every
    fpga/gen/gated_clocks.txt identifier this run resolved to a
    hierarchical handle, and every one it could not (with why), so
    monitor completeness is stated, not assumed. See
    conftest_helpers.resolve_gated_clock_handles()'s own docstring."""
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
    """Print every OB value change observed this run (conftest_helpers.
    _track_ob) -- the report wants the TRAJECTORY (e.g. the POISON byte
    0xFF appearing before the real answer), not just the final value."""
    trace = getattr(_track_ob, "trace", [])
    for t_ns, v in trace:
        cocotb.log.info(f"  OB trace: t={t_ns}ns OB=0x{v:02X}")


def _assert_no_violations():
    """Liveness self-check FIRST (self-review finding): "0 violations" is
    meaningless if the monitor never actually got a qualifying sample to
    check. qualifying_samples counts clk_sys ticks where clk_prev==1 AND
    clk_now==1 -- the same gate the violation check itself uses -- so a
    monitor that silently never fired (dut.clk stuck unresolved, wrong
    handle, etc.) fails LOUD here instead of passing by accident."""
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


@cocotb.test()
async def milestone_free_runs_to_4d(dut):
    """LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT -> OB=0x4D.
    Oracle: docs/notes/progrom_gen.py's own simulate(), via
    oracle_final_ob() -- never hand-typed. The leading LDAI 0xFF; OUT
    POISONS OB first (CLAUDE.md: U35/OB has no reset, the machine
    free-runs at power-up, so OB always already holds a previous run's
    answer) -- OB is therefore expected to read 0xFF partway through and
    only 0x4D once the run has actually reached the SECOND OUT, at HALT.
    """
    exp = oracle_final_ob("real")
    # prog_hex here is a LABEL, not a selector -- the elaborated ROM was
    # already fixed by the `make` invocation's DINO_PROG_HEX generic
    # override (defaults to hex/PROG.hex, this line's own value) BEFORE
    # this Python code ever ran; passing a different path here would not
    # change what the machine actually executes, only what gets logged
    # (run_program()'s own docstring explains why a GHDL generic can't be
    # runtime-selected). If this test is ever invoked with a mismatched
    # DINO_PROG_HEX override, the oracle assertion below still fails --
    # loudly, on the wrong OB -- so a label/reality mismatch cannot pass
    # silently, but it also will not name itself as a mismatch.
    prog_hex = os.path.join(HEX_DIR, "PROG.hex")
    ob = await run_program(dut, prog_hex, switches=0x00, max_us=MAX_US)
    _report_monitor()
    _report_ob_trace()
    _assert_no_violations()
    assert ob == exp, (
        f"OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('real'), never hand-typed)")


@cocotb.test()
async def in_tracks_switches(dut):
    """IN replaces the second addend with SW1 through the io '244
    switch-gate (fpga/gen/input_output.vhd). Bench-recorded settings
    (CLAUDE.md): SW1=0x01 -> 0x30, SW1=0x1E -> 0x4D (the SAME 0x4D the
    milestone image proves, over a different operand path -- only the
    SOURCE changed). Both cross-checked against
    progrom_gen.simulate(switches=sw) via oracle_final_ob() -- a
    disagreement between the bench-recorded constant and the oracle would
    itself be a finding, so it is asserted explicitly below rather than
    silently trusting one over the other.

    dip_sw polarity: per Task 10's own header note
    (test_module_input_output.py), dip_sw is a plain TB-driven port with
    NO inversion between it and w in this VHDL boundary -- the switch's
    real-world active-low pull-up (SW1/R17-24) is physically OUTSIDE the
    modeled entity (Task 8's excluded-parts boundary). This TB therefore
    drives dip_sw with the RAW byte it wants w/IN to read, exactly like
    that module test already does -- no double inversion.
    """
    # Same label-not-selector caveat as milestone_free_runs_to_4d's own
    # prog_hex -- this test MUST be invoked with
    # DINO_PROG_HEX=hex/PROG_in.hex (see this file's own header) or the
    # elaborated ROM will be the wrong image; the oracle assertions below
    # still catch that (loudly), they just won't name it as a
    # label/reality mismatch.
    prog_hex = os.path.join(HEX_DIR, "PROG_in.hex")
    cases = ((0x01, 0x30), (0x1E, 0x4D))
    for i, (sw, want_bench) in enumerate(cases):
        exp = oracle_final_ob("in", switches=sw)
        assert exp == want_bench, (
            f"fixture sanity: oracle_final_ob('in', switches=0x{sw:02X}) "
            f"= 0x{exp:02X}, want the bench-recorded 0x{want_bench:02X} "
            f"(CLAUDE.md) -- oracle and bench log disagree, investigate "
            f"before trusting either")
        if i == 0:
            ob = await run_program(dut, prog_hex, switches=sw, max_us=MAX_US)
        else:
            ob = await rerun(dut, switches=sw, max_us=MAX_US)
        assert ob == exp, (
            f"switches=0x{sw:02X}: OB=0x{ob:02X}, want 0x{exp:02X} "
            f"(oracle_final_ob('in', switches=0x{sw:02X}))")
    _report_monitor()
    _report_ob_trace()
    _assert_no_violations()
