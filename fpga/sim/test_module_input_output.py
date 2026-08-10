import cocotb
from cocotb.triggers import Timer

# Module testbench (Task 10, copying Task 9's pattern) -- input_output.
# Stimulus/assertions touch ONLY fpga/gen/input_output.vhd's own contract
# ports (clk_sys, ob, n_sw_out, w, dip_sw) -- the same signals
# tests/dino_bringup/src/mod_io.c's bind() DRIVEs/SAMPLEs on the real
# rig. Every test's docstring names the mod_io.c rig test it ports.
#
# FINDING, not assumed -- read straight off fpga/gen/input_output.vhd:
# this sheet implements ONLY the switch-gate half of the I/O board.
#   switch_gate1 '244  A = dip_sw0-7, Y = w0-7, BOTH ~G tied to n_sw_out
#             -- a PLAIN pass-through (no inverter in the netlist), so
#             switches reach w only while n_sw_out is asserted (LOW);
#             otherwise w is high-Z.
# The `ob` port is declared on this entity but IS NEVER REFERENCED
# anywhere in its architecture body (confirmed by reading the generated
# file, not assumed) -- it's a dead wire here. This matches
# mod_io.c's own header comment exactly: "R9-R16 OB0-7 -> LED anodes...
# In the real machine OB comes from the OUT register on the REGISTERS
# board -- here the rig substitutes for it" -- i.e. on the real board the
# LEDs are a PASSIVE load (no logic) fed directly off the OB bus, and the
# actual "OB latch" this task's brief asks for is U35 on
# registers_a_b.kicad_sch, already covered by
# test_module_registers_a_b.py's test_registers_outreg_ob_latch. This
# file therefore covers this module's OTHER required half only ("PROG_in
# switch path through the io '244"); test_input_output_ob_is_dead_wire
# below is the evidence for the OB half's absence, not a substitute for it.
#
# Bench polarity note (brief pointer, microcode_gen.py:137's IN
# instruction comment): "SW1 is ACTIVE LOW at the bench: R17-R24 pull
# IS0-7 high, the switch pulls down, so a CLOSED switch reads 0." That
# pull-up circuit is PHYSICALLY OUTSIDE this VHDL entity's boundary (SW1/
# R17-24 are EXCLUDED non-chip parts per Task 8's boundary table) --
# dip_sw is a plain TB-driven `in` port here with NO inversion in the
# netlist between it and w, so this TB drives dip_sw with the RAW
# electrical byte it wants w to read (matching CLAUDE.md's own bench log,
# "SW1=0x01 gives 0x30" -- 0x2F+0x01=0x30, the literal byte value, not
# its bitwise complement) -- getting this backwards would silently invert
# every pattern below without failing (a passthrough test doesn't catch
# its own polarity if BOTH sides are inverted the same way), so every
# comment here says explicitly which raw byte is being driven.
SETTLE = 50


async def _bind_idle(dut):
    # clk_sys is a dead port on this purely combinational sheet -- no
    # clock needed. Deposit dip_sw/n_sw_out/ob as the very first
    # statements (no clocked model on this sheet to race against, but
    # matches the discipline established elsewhere in this task).
    dut.dip_sw.value = 0
    dut.n_sw_out.value = 1     # port disabled (idle)
    dut.ob.value = 0
    await Timer(SETTLE, unit="ns")


async def _settle(dut):
    await Timer(SETTLE, unit="ns")


@cocotb.test()
async def test_input_output_switch_passthrough_and_tristate(dut):
    """Ports mod_io.c t_io_switches + t_io_tristate: switch_pattern (raw
    bytes 0x00/0xFF/0xC5/0x3A driven directly on dip_sw, no inversion --
    see the header's polarity note), plus the tristate contract that lets
    the switch port share w with every other bus source (ALU/MAR/MDR)."""
    await _bind_idle(dut)
    for pat in (0x00, 0xFF, 0xC5, 0x3A):
        dut.dip_sw.value = pat
        dut.n_sw_out.value = 0     # asserted (enabled)
        await _settle(dut)
        got = int(dut.w.value)
        assert got == pat, (
            f"w: dip_sw=0x{pat:02X} (~{{SW_OUT}} asserted) -> 0x{got:02X}, "
            f"want 0x{pat:02X} (plain pass-through, no inversion in the netlist)"
        )
        dut.n_sw_out.value = 1     # released
        await _settle(dut)
        w_str = str(dut.w.value)
        assert all(c == "Z" for c in w_str), (
            f"w: dip_sw=0x{pat:02X} ~{{SW_OUT}} released -> {w_str}, want all-Z"
        )

    # per-bit walk, both levels -- proves all 8 wires independently.
    for b in range(8):
        v1 = 1 << b
        dut.dip_sw.value = v1
        dut.n_sw_out.value = 0
        await _settle(dut)
        got = int(dut.w.value)
        assert got == v1, f"w: walk1 bit{b} dip_sw=0x{v1:02X} -> 0x{got:02X}"
        v0 = (~v1) & 0xFF
        dut.dip_sw.value = v0
        await _settle(dut)
        got = int(dut.w.value)
        assert got == v0, f"w: walk0 bit{b} dip_sw=0x{v0:02X} -> 0x{got:02X}"
        dut.n_sw_out.value = 1
        await _settle(dut)


@cocotb.test()
async def test_input_output_ob_is_dead_wire(dut):
    """Ports mod_io.c t_io_isolation's spirit (LED side and switch side
    share no nets), plus the finding this file's header documents: `ob`
    is declared on this entity but never referenced in its architecture,
    so driving it through every value can never move w -- confirms
    (doesn't just assert) that the OB-latch half of this module's brief
    minimum genuinely lives elsewhere (registers_a_b.vhd's U35)."""
    await _bind_idle(dut)
    dut.dip_sw.value = 0xC5
    dut.n_sw_out.value = 0
    await _settle(dut)
    base = int(dut.w.value)
    assert base == 0xC5, f"w: baseline dip_sw=0xC5 -> 0x{base:02X}"
    for ob_v in (0xFF, 0x00, 0xAA, 0x55):
        dut.ob.value = ob_v
        await _settle(dut)
        got = int(dut.w.value)
        assert got == base, (
            f"w: ob driven to 0x{ob_v:02X} -> 0x{got:02X}, want unchanged "
            f"0x{base:02X} (ob is an unused/dead port on this sheet)"
        )
