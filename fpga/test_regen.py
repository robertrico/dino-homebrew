import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# Covering test for Task 8's review fix #1: proves the `microcode` sheet
# entity's DEFAULT generics (u9_init_file/u15_init_file, NOT overridden
# here -- the exact "an override-less run" scenario the review flagged)
# resolve correctly and load REAL burned content when this test runs from
# the documented directory (`cd fpga && make -f Makefile.regen`, i.e. THIS
# file's own directory, matching the elaboration gate's `cd fpga &&
# ghdl -a ... gen/*.vhd`). MEMORY_INSTANCES' defaults (docs/notes/
# fpga_gen.py) are "sim/hex/U9.hex"/"sim/hex/U15.hex" -- correct ONLY
# relative to `fpga/`; running from anywhere else (e.g. `fpga/gen/`) would
# either hard-fail opening a nonexistent file or (per ttl_at28c64b.vhd's
# `load_mem`, unchanged by this task -- see MEMORY_INSTANCES' comment)
# silently load an all-zero ROM. Byte 0 of both roms/U9.bin and
# roms/U15.bin is genuinely non-zero, so this test distinguishes a real
# load from that silent-zero failure mode, not just from a loud one.
#
# Address derivation (read straight off the generated gen/microcode.vhd,
# not assumed): T(0..3) -> a0..a3, IRB(0..7) -> a4..a11 (both '244 buffers
# permanently enabled, plain wire-through, a12 tied '0') -- so T=0/IRB=0
# addresses ROM location 0 directly.


@cocotb.test()
async def dino_core_regen_hex_loads_from_documented_rundir(dut):
    # U9/U15 (AT28C64B) gained a clk_sys-REGISTERED read (Task-13 rework
    # item 2) -- clk_sys has to actually be running for their internal `q`
    # register to leave its t=0 'U' init, so start it here.
    cocotb.start_soon(Clock(dut.clk_sys, 10, unit="ns").start())
    dut.t.value = 0
    dut.irb.value = 0
    await Timer(50, unit="ns")  # settle -- 5 clk_sys cycles, comfortable margin

    with open("../roms/U9.bin", "rb") as f:
        want_lo = f.read(1)[0]
    with open("../roms/U15.bin", "rb") as f:
        want_hi = f.read(1)[0]
    assert want_lo != 0 or want_hi != 0, (
        "fixture sanity: byte 0 of both roms/U9.bin and roms/U15.bin is "
        "0x00 -- this test could no longer distinguish a real load from a "
        "silently zero-filled wrong-path one")

    got_lo = int(dut.cw.value) & 0xFF  # cw(7 downto 0) == U9's io0-io7
    assert got_lo == want_lo, (
        f"microcode's u9_init_file default did not load roms/U9.bin's "
        f"real byte 0: got 0x{got_lo:02x}, want 0x{want_lo:02x} -- wrong "
        f"default path, or run from the wrong directory")

    # U15's byte 0 is spread across cw(8) + the 7 composite outputs
    # (io0..io7, gen/microcode.vhd's own port map names them explicitly).
    got_hi = (
        (int(dut.cw.value) >> 8 & 1)
        | (int(dut.cw9_eq_sa2.value) << 1)
        | (int(dut.cw10_eq_sa1.value) << 2)
        | (int(dut.cw11_eq_sa0.value) << 3)
        | (int(dut.cw12_eq_end.value) << 4)
        | (int(dut.cw13_eq_pc_up.value) << 5)
        | (int(dut.cw14_eq_pc_mar_mux.value) << 6)
        | (int(dut.cw15_eq_halt.value) << 7)
    )
    assert got_hi == want_hi, (
        f"microcode's u15_init_file default did not load roms/U15.bin's "
        f"real byte 0: got 0x{got_hi:02x}, want 0x{want_hi:02x} -- wrong "
        f"default path, or run from the wrong directory")
