import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# Module testbench -- stack_pointer (schematic 2026-08-10). Stimulus and
# assertions touch ONLY fpga/gen/stack_pointer.vhd's own contract ports
# (clk_sys, clk, n_sp_up, n_sp_down, n_sp_lo_load, n_sp_hi_load,
# n_sp_lo_out, n_sp_hi_out, mdr_i, mdr_o).
#
# Gate structure read straight off fpga/gen/stack_pointer.vhd, itself
# generated from stack_pointer.kicad_sch:
#
#   U63-U66 '169  the 16-bit counter, CP = clk (NOT ~clk -- see below).
#                 P0-P3 of both pairs sit on the SAME mdr byte; which pair
#                 captures is decided purely by ~PE:
#                     U63+U64 <- n_sp_lo_load     -> SP0-7
#                     U65+U66 <- n_sp_hi_load     -> SP8-15
#                 U/~D = n_sp_down on all four (zero gates: the active-low
#                 decode IS the direction level).
#   U69 '08       n_sp_ce = AND(n_sp_up, n_sp_down) -> ~CEP on all four,
#                 and ~CET on U63 only. The rest chain ~TC -> ~CET:
#                     U63 -> U64 -> U65 -> U66
#                 IN WEIGHT ORDER. The schematic originally had this as
#                 U63 -> U65 -> U64 -> U66, which increments correctly for
#                 a few counts and then carries into the wrong nibble --
#                 counter169_crosses_the_byte_boundary below is the check
#                 that would have caught it.
#   U67/U68 '245  readback, DIR=+5V (A->B, SP -> MDR), CE = n_sp_hi_out /
#                 n_sp_lo_out. The '169 Q pins are totem-pole and cannot
#                 tri-state, so these buffers are the ONLY place a choice
#                 can happen -- which is why the HI byte needs its own net
#                 set (SP8-15) rather than sharing SP0-7.
#
# SP clocks on CLK, not ~CLK, and that is deliberate: LE = NOR(~LOAD, CLK)
# makes MAR/registers transparent WHILE CLK IS LOW, so a ~CLK-clocked SP
# would update at the start of that window and a row doing
# `SRC=SP_LO, DST=MAR_LO, MISC=SP_DOWN` would land the POST-decrement value
# in MAR. On CLK, SP updates at the T-state boundary, after every
# transparent latch has closed.
#
# A '169 has no clear, so the model powers up non-zero on purpose
# (ttl_74ls169.vhd's por_value). Every test here establishes state with an
# explicit load rather than assuming any reset value.
SETTLE = 50   # ns -- >3 clk_sys cycles
HOLD = 250    # ns -- half-period of a slow, machine-realistic CLK


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk_sys, 10, unit="ns").start())
    dut.clk.value = 0
    dut.n_sp_up.value = 1
    dut.n_sp_down.value = 1
    dut.n_sp_lo_load.value = 1
    dut.n_sp_hi_load.value = 1
    dut.n_sp_lo_out.value = 1
    dut.n_sp_hi_out.value = 1
    dut.mdr_i.value = 0
    await Timer(SETTLE, unit="ns")


async def _settle(dut):
    await Timer(SETTLE, unit="ns")


async def _tick(dut):
    """One machine CLK rising edge, returned low."""
    dut.clk.value = 1
    await Timer(HOLD, unit="ns")
    dut.clk.value = 0
    await Timer(HOLD, unit="ns")


async def _load(dut, lo=None, hi=None):
    if lo is not None:
        dut.mdr_i.value = lo
        dut.n_sp_lo_load.value = 0
        await _tick(dut)
        dut.n_sp_lo_load.value = 1
        await _settle(dut)
    if hi is not None:
        dut.mdr_i.value = hi
        dut.n_sp_hi_load.value = 0
        await _tick(dut)
        dut.n_sp_hi_load.value = 1
        await _settle(dut)


async def _read(dut, half):
    """half = 'lo' | 'hi'. Returns the byte the readback '245 puts on mdr_o."""
    sig = dut.n_sp_lo_out if half == "lo" else dut.n_sp_hi_out
    sig.value = 0
    await _settle(dut)
    got = int(dut.mdr_o.value)
    sig.value = 1
    await _settle(dut)
    return got


async def _count(dut, n, down=False):
    dut.n_sp_up.value = 1 if down else 0
    dut.n_sp_down.value = 0 if down else 1
    for _ in range(n):
        await _tick(dut)
    dut.n_sp_up.value = 1
    dut.n_sp_down.value = 1
    await _settle(dut)


@cocotb.test()
async def sp_load_and_readback_is_a_mirror_witness(dut):
    """Two DIFFERENT bytes, so a swapped lo/hi pair or a reversed nibble
    cannot pass. A round trip with one value is permutation-blind -- the
    lesson the flipped PORTF->MDR bank taught this project."""
    await _start(dut)
    await _load(dut, lo=0x3C, hi=0xA5)

    got = await _read(dut, "lo")
    assert got == 0x3C, f"SP lo readback -> 0x{got:02X}, want 0x3C"
    got = await _read(dut, "hi")
    assert got == 0xA5, (
        f"SP hi readback -> 0x{got:02X}, want 0xA5 "
        f"(0x3C would mean both '245s see the same net set; a nibble-swapped "
        f"value would mean Q0-Q3 were wired by pin NUMBER rather than by name)"
    )


@cocotb.test()
async def sp_holds_when_neither_up_nor_down_is_asserted(dut):
    """The default state. SP must not move on the ~95% of T-states that have
    nothing to do with the stack, so a model that ORs the enables or inverts
    only one of them would corrupt SP on unrelated instructions."""
    await _start(dut)
    await _load(dut, lo=0x11, hi=0x22)

    for _ in range(4):
        await _tick(dut)
    assert await _read(dut, "lo") == 0x11, "SP lo moved with both enables idle"
    assert await _read(dut, "hi") == 0x22, "SP hi moved with both enables idle"


@cocotb.test()
async def sp_counts_both_directions(dut):
    await _start(dut)
    await _load(dut, lo=0x10, hi=0x00)

    await _count(dut, 3)
    assert await _read(dut, "lo") == 0x13, "three SP_UP ticks did not add 3"

    await _count(dut, 5, down=True)
    got = await _read(dut, "lo")
    assert got == 0x0E, (
        f"SP after 3 up then 5 down -> 0x{got:02X}, want 0x0E. If this reads "
        f"0x18 the direction level is stuck high -- the '163 trap, where pin 1 "
        f"gets strapped like a ~MR instead of carrying ~{{SP_DOWN}}"
    )


@cocotb.test()
async def sp_crosses_the_byte_boundary(dut):
    """The ~TC cascade must run U63 -> U64 -> U65 -> U66, in weight order.

    This is the check that catches a crossed carry chain. The schematic was
    first drawn U63 -> U65 -> U64 -> U66, which counts correctly for a while
    and then carries into the wrong nibble -- on the bench that reads as "the
    stack works until it doesn't", which is the worst possible failure shape.

    0x00FF + 1 must be 0x0100: carry has to propagate out of SP3 into SP4,
    out of SP7 into SP8 (the byte boundary, U64 -> U65), and stop there.
    """
    await _start(dut)
    await _load(dut, lo=0xFF, hi=0x00)

    await _count(dut, 1)
    lo, hi = await _read(dut, "lo"), await _read(dut, "hi")
    assert (hi, lo) == (0x01, 0x00), (
        f"0x00FF + 1 -> 0x{hi:02X}{lo:02X}, want 0x0100 "
        f"(carry must cross U64 -> U65, the byte boundary)"
    )

    # And back down across the same boundary -- a borrow is the mirror case
    # and exercises the direction-dependent terminal count.
    await _count(dut, 1, down=True)
    lo, hi = await _read(dut, "lo"), await _read(dut, "hi")
    assert (hi, lo) == (0x00, 0xFF), (
        f"0x0100 - 1 -> 0x{hi:02X}{lo:02X}, want 0x00FF (borrow across the "
        f"byte boundary)"
    )


@cocotb.test()
async def sp_releases_the_bus_when_neither_readback_is_enabled(dut):
    """Both '245s off -> mdr_o floats. SP shares MDR0-7 with ROM, RAM and
    all three registers; a buffer that fails to release would fight every
    one of them."""
    await _start(dut)
    await _load(dut, lo=0x5A, hi=0xC3)

    dut.n_sp_lo_out.value = 1
    dut.n_sp_hi_out.value = 1
    await _settle(dut)
    val = dut.mdr_o.value
    assert "Z" in str(val).upper(), (
        f"mdr_o with both readback '245s disabled -> {val}, want high-Z on "
        f"every bit"
    )
