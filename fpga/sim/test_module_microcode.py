import os
import sys
from cocotb.clock import Clock
from cocotb.triggers import Timer

import cocotb

# Module testbench (Task 10, copying Task 9's pattern) -- microcode.
# Stimulus/assertions touch ONLY fpga/gen/microcode.vhd's own contract
# ports (clk_sys, irb, t, cw, cw11_eq_sa0, cw10_eq_sa1, cw9_eq_sa2,
# cw12_eq_end, cw15_eq_halt, cw14_eq_pc_mar_mux, cw13_eq_pc_up) -- the
# same signals tests/dino_bringup/src/mod_microcode.c's bind()
# DRIVEs/SAMPLEs on the real rig.
#
# THE required minimum for this module ("ROM word for known (opcode,T)
# pairs matches microcode_gen.build_real() -- IMPORT it, never retype
# bytes") is honored literally: build_real()/OPCODES are IMPORTED from
# docs/notes/microcode_gen.py, the exact module CLAUDE.md's own state
# section credits with catching the SA-field bit-reversal bug (ADD
# executing as AND) -- retyping any word here would silently recreate
# the class of bug that discovery closed.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "docs", "notes"))
from microcode_gen import OPCODES, build_real  # noqa: E402

# Address derivation read straight off fpga/gen/microcode.vhd (Task 8's
# generated output): U17 wires t(0..3) -> a0..a3, U16 wires
# irb(0..7) -> a4..a11 (both '244s permanently enabled, plain wire-
# through, a12 tied '0') -- so row = opcode*16 + T, matching
# build_real()'s own indexing exactly (same derivation
# fpga/test_regen.py's covering test already uses for dino_core's whole-
# machine default-generic proof).
#
# CW bit assembly (also matching fpga/test_regen.py's own formula, not
# reinvented here): cw(8 downto 0) carries bits 0-8; the 7 composite
# outputs carry bits 9-15 in port-declaration order (cw9_eq_sa2=bit9,
# cw10_eq_sa1=bit10, cw11_eq_sa0=bit11, cw12_eq_end=bit12,
# cw13_eq_pc_up=bit13, cw14_eq_pc_mar_mux=bit14, cw15_eq_halt=bit15).
#
# U9/U15 (AT28C64B) gained a clk_sys-REGISTERED read (Task-13 rework item
# 2) -- clk_sys now has to actually be RUNNING for their internal `q`
# register to ever leave its t=0 'U' init, so _bind_idle starts it; SETTLE
# (50ns, 5 clk_sys cycles at the 10ns period used everywhere else in this
# repo) already comfortably covers the one extra clk_sys tick of latency.
SETTLE = 50

REAL_WORDS = build_real()


async def _bind_idle(dut):
    cocotb.start_soon(Clock(dut.clk_sys, 10, unit="ns").start())
    dut.irb.value = 0
    dut.t.value = 0
    await Timer(SETTLE, unit="ns")


async def _mc_read(dut, row):
    dut.irb.value = (row >> 4) & 0xFF
    dut.t.value = row & 0xF
    await Timer(SETTLE, unit="ns")
    return (
        int(dut.cw.value)
        | (int(dut.cw9_eq_sa2.value) << 9)
        | (int(dut.cw10_eq_sa1.value) << 10)
        | (int(dut.cw11_eq_sa0.value) << 11)
        | (int(dut.cw12_eq_end.value) << 12)
        | (int(dut.cw13_eq_pc_up.value) << 13)
        | (int(dut.cw14_eq_pc_mar_mux.value) << 14)
        | (int(dut.cw15_eq_halt.value) << 15)
    )


@cocotb.test()
async def test_microcode_known_rows_match_build_real(dut):
    """Ports mod_microcode.c t_microcode_order/t_microcode_split's spirit
    (spot rows against the REAL burn), but the expectation comes straight
    from the IMPORTED build_real(), not a retyped constant -- this
    module's REQUIRED minimum. Covers: the universal T0 fetch, an ALU op
    row (the exact class of row the SA-bit-reversal bug hid in), an
    immediate-load row, HALT, and an undefined (opcode,T) row that must
    read back as safe-fill."""
    await _bind_idle(dut)
    rows = {
        "FETCH (opcode=0x00,T=0)": 0x00 * 16 + 0,
        "ADD T1 (opcode=0x41,T=1)": OPCODES["ADD"] * 16 + 1,
        "SUB T1 (opcode=0x42,T=1)": OPCODES["SUB"] * 16 + 1,
        "LDAI T1 (opcode=0x11,T=1)": OPCODES["LDAI"] * 16 + 1,
        "OUT T1 (opcode=0x51,T=1)": OPCODES["OUT"] * 16 + 1,
        "HALT T1 (opcode=0xFF,T=1)": OPCODES["HALT"] * 16 + 1,
        "undefined (LDBI T3, safe-fill)": OPCODES["LDBI"] * 16 + 3,
    }
    for label, row in rows.items():
        got = await _mc_read(dut, row)
        want = REAL_WORDS[row]
        assert got == want, (
            f"cw+composites: row 0x{row:03X} ({label}) -> 0x{got:04X}, "
            f"want 0x{want:04X} (build_real()[0x{row:03X}])"
        )


@cocotb.test()
async def test_microcode_full_image_matches_build_real(dut):
    """Ports mod_microcode.c t_microcode_crc's spirit (full-ROM verify),
    strengthened to an exact per-row compare against the imported
    build_real() image instead of a CRC -- all 4096 rows, so a
    mis-packed word anywhere (not just at the spot-checked rows above)
    fails here by ROW NUMBER, not just by a changed checksum."""
    await _bind_idle(dut)
    bad = 0
    first_bad = None
    for row in range(4096):
        got = await _mc_read(dut, row)
        want = REAL_WORDS[row]
        if got != want:
            bad += 1
            if first_bad is None:
                first_bad = (row, got, want)
    assert bad == 0, (
        f"{bad}/4096 rows mismatch build_real(); first at "
        f"row=0x{first_bad[0]:03X} got=0x{first_bad[1]:04X} "
        f"want=0x{first_bad[2]:04X}"
    )
