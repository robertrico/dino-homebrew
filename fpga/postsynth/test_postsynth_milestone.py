"""Restated synthesis gate 5: the POST-SYNTHESIS netlist runs the program.

Everything else in this repo simulates the SOURCE VHDL. This file
simulates what synthesis actually produced -- `write_verilog` of the
netlist that comes out of `synth_ecp5`'s coarse stage (flatten,
fpga/synth/bus_resolve.ys's shared-bus resolution, opt/fsm/share/alumacc,
`memory -nomap`), re-elaborated in Icarus Verilog with no VHDL in sight --
and asserts it still reaches OB=0x4D on the milestone program.

Why the coarse-stage netlist and not the fully ECP5-mapped one: yosys's
own ECP5 cell library has NO functional model for DP16KD (
share/yosys/lattice/cells_sim_ecp5.v declares the module with its
INITVAL_* parameters and an EMPTY body), so a BRAM-mapped netlist is not
simulatable by construction, in any simulator, without hand-writing a
DP16KD behavioural model -- and a hand-written model that is subtly wrong
would produce a false PASS, which is worse than not running the gate.
The coarse-stage netlist is the last simulatable point, and it is the one
that carries all of the risk: it is where Task 13's CRITICAL FINDING
(opt_clean eating the program ROM and RAM) happened, and where this
rework's own bus resolution happens. Downstream of it, BRAM techmap and
LUT mapping are evidenced separately and structurally -- four `mapping
memory ... via $__DP16KD_` lines with zero "using FF mapping", 39 DP16KD
placed, and place-and-route + timing closure on the real netlist.

Run: `make -C fpga/postsynth` (see that Makefile).
"""
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "sim")))

# The SAME oracle and the SAME clock cadence the VHDL-side whole-core
# suite uses -- imported, never re-typed. If these ever drift, this gate
# drifts with them by construction.
from conftest_helpers import (  # noqa: E402
    CLK_SYS_PERIOD_NS, Y1_HIGH_CYCLES, Y1_LOW_CYCLES, oracle_final_ob,
)

MAX_US = 500


async def _drive_clk4m_y1(dut):
    dut.clk4m_y1.value = 0
    while True:
        await ClockCycles(dut.clk_sys, Y1_LOW_CYCLES)
        dut.clk4m_y1.value = 1
        await ClockCycles(dut.clk_sys, Y1_HIGH_CYCLES)
        dut.clk4m_y1.value = 0


@cocotb.test()
async def postsynth_milestone_free_runs_to_4d(dut):
    """LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT -> OB=0x4D,
    executed by the synthesized netlist. Oracle is
    progrom_gen.simulate() via oracle_final_ob('real'), same as the
    VHDL-side test -- never hand-typed.

    The reset sequence is deliberately NOT conftest_helpers._arm_reset():
    that one waits on `dut.clk`, dino_core's internal machine clock,
    which a flattened netlist need not still expose under that name. Held
    here for a fixed, generous span instead -- the machine is fully
    static (CLAUDE.md: the '121 one-shot is gone), so there is no minimum
    or maximum hold time to get right, and the HALT wait below is what
    actually sequences the run.
    """
    exp = oracle_final_ob("real")

    dut.dip_sw.value = 0
    dut.btn_reset_n.value = 0
    dut.clk4m_y1.value = 0
    cocotb.start_soon(Clock(dut.clk_sys, CLK_SYS_PERIOD_NS, unit="ns").start())
    await Timer(CLK_SYS_PERIOD_NS, unit="ns")
    cocotb.start_soon(_drive_clk4m_y1(dut))

    # Hold reset well past several machine-CLK periods (clk_sys/100), then
    # release and let it free-run.
    await ClockCycles(dut.clk_sys, 1000)
    dut.btn_reset_n.value = 1

    max_cycles = int(MAX_US * 1000 / CLK_SYS_PERIOD_NS)
    for _ in range(max_cycles):
        await RisingEdge(dut.clk_sys)
        if str(dut.halt.value) == "1":
            break
    else:
        raise AssertionError(
            f"post-synthesis netlist never reached HALT within {MAX_US}us "
            f"(ob_led={dut.ob_led.value}) -- NOT a timeout to paper over: "
            f"the VHDL-side milestone reaches HALT on the same stimulus, "
            f"so a divergence here is a synthesis-introduced defect")

    ob = int(dut.ob_led.value)
    cocotb.log.info(f"post-synthesis netlist: OB=0x{ob:02X} at HALT")
    assert ob == exp, (
        f"post-synthesis netlist OB=0x{ob:02X} at HALT, want 0x{exp:02X} "
        f"(oracle_final_ob('real')) -- synthesis changed machine "
        f"behaviour")
